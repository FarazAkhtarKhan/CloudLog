import { Play, RotateCcw, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useToast } from "../lib/toast";
import { Empty, ErrorNotice, Panel, Sev } from "../components/ui";
import { LEVELS } from "../config";
import { api } from "../lib/api";
import { fileName, ms } from "../lib/format";
import { useLive, usePoll } from "../lib/hooks";

const OUTCOME = { opened: "Opened", reopened: "Reopened", updated: "Updated", duplicate: "Already counted" };

/** Polls the pipeline-runs table until the processor reports on our file. */
function useTrace(upload) {
  const [result, setResult] = useState({ uri: null, run: null, timedOut: false });
  useEffect(() => {
    if (!upload) return undefined;
    let alive = true;
    const started = Date.now();
    const tick = async () => {
      try {
        const { runs } = await api.runs(15);
        const found = runs.find((r) => r.s3_uri === upload.s3_uri);
        if (found && alive) return setResult({ uri: upload.s3_uri, run: found, timedOut: false });
      } catch {
        /* keep polling */
      }
      if (!alive) return;
      if (Date.now() - started > 30000) return setResult({ uri: upload.s3_uri, run: null, timedOut: true });
      setTimeout(tick, 700);
    };
    tick();
    return () => { alive = false; };
  }, [upload]);
  return result.uri && result.uri === upload?.s3_uri ? result : { run: null, timedOut: false };
}

function Step({ state, title, children, n }) {
  return (
    <li className={`step ${state}`}>
      <span className="step-mark" aria-hidden="true">{state === "done" || state === "alert" ? "✓" : n}</span>
      <span className="step-title">{title}{state === "wait" && <span className="visually-hidden"> (in progress)</span>}</span>
      {children && <div className="step-detail">{children}</div>}
    </li>
  );
}

function Trace({ upload, run, timedOut }) {
  if (!upload) {
    return <Empty title="Pick a scenario">Its log file is uploaded to S3 and you can follow it through each cloud service here.</Empty>;
  }
  const latency = run ? new Date(run.started_at) - new Date(upload.uploaded_at) : null;
  const waiting = run ? "done" : timedOut ? "" : "wait";
  const after = run ? "done" : "";
  const alerts = run?.alerts || [];
  return (
    <ol className="steps panel-body">
      <Step n={1} state="done" title="Uploaded to the S3 bucket">
        <span className="mono">{upload.s3_key}</span>, {upload.lines.length} lines
      </Step>
      <Step n={2} state={waiting} title="S3 event invoked the processor Lambda">
        {run && `Started ${ms(Math.max(latency, 0))} after the upload and ran for ${ms(run.duration_ms)}.`}
        {timedOut && "No report after 30 s. Check the processor's CloudWatch logs and the dead-letter queue."}
        {!run && !timedOut && "Waiting for the S3 notification…"}
      </Step>
      <Step n={3} state={after} title="Validated, masked and stored in DynamoDB">
        {run && (
          <>
            {run.stored} lines stored, {run.rejected} rejected
            {run.pii_redacted > 0 && `, ${run.pii_redacted} with personal data masked`}.
            {run.rejections?.length > 0 && (
              <ul>{run.rejections.map((r) => <li key={r.line_number}>Line {r.line_number}: <span className="mono">{r.reason}</span>, {r.detail}</li>)}</ul>
            )}
          </>
        )}
      </Step>
      <Step n={4} state={after} title="Detection rules applied">
        {run && (run.detections?.length ? (
          <ul>
            {run.detections.map((d) => (
              <li key={d.incident_id}>
                <Sev level={d.severity} /> {OUTCOME[d.outcome]}{d.escalated && " and escalated"}:{" "}
                <a href={`#/incidents/${d.incident_id}`}>{d.title}</a>
              </li>
            ))}
          </ul>
        ) : "No rule matched, so no incident was created.")}
      </Step>
      <Step n={5} state={run ? (alerts.length ? "alert" : "done") : ""} title="SNS alert">
        {run && (alerts.length
          ? <ul>{alerts.map((a) => <li key={a.message_id}>Published “{a.subject}”</li>)}</ul>
          : "Nothing critical, so nobody was paged.")}
      </Step>
    </ol>
  );
}

function FileView({ upload, run }) {
  const rejected = new Set((run?.rejections || []).map((r) => r.line_number));
  return (
    <div className="terminal">
      <div className="terminal-head">
        <span>{upload ? fileName(upload.s3_key) : "log file"}</span>
        <span>{upload ? `${upload.lines.length} lines` : ""}</span>
      </div>
      <div className="terminal-body" style={{ maxHeight: 300 }}>
        {upload ? upload.lines.map((line, i) => (
          <div key={i} className={`raw-line${rejected.has(i + 1) ? " bad" : ""}`}>
            <span className="ln">{i + 1}</span>{line || "(blank line)"}
          </div>
        )) : <div className="terminal-empty">The generated JSON Lines file appears here.</div>}
      </div>
    </div>
  );
}

export default function Simulator() {
  const { session, refresh } = useLive();
  const toast = useToast();
  const canRun = session.role !== "Viewer";
  const { data: catalog } = usePoll(() => api.scenarios(), [], null);
  const { data: rules } = usePoll(() => api.rules(), [], null);
  const [upload, setUpload] = useState(null);
  const [current, setCurrent] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [custom, setCustom] = useState({ service: "checkout-api", level: "ERROR", message: "Unhandled NullPointerException in CartController", error_code: "CART_NPE", repeat: 1 });
  const { run, timedOut } = useTrace(upload);
  const traceRef = useRef(null);
  const reported = useRef(null);

  useEffect(() => {
    if (run && reported.current !== run.run_id) {
      reported.current = run.run_id;
      refresh();
    }
  }, [run, refresh]);

  async function launch(body, label) {
    setBusy(true);
    setError(null);
    setCurrent(label);
    try {
      const result = await api.simulate(body);
      setUpload(result);
      traceRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Delete every stored log line, incident and pipeline run?")) return;
    try {
      const { deleted } = await api.reset();
      toast("Demo data deleted", `${deleted.events} log lines, ${deleted.incidents} incidents, ${deleted.runs} runs`);
      setUpload(null);
      refresh();
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="stack">
      {!canRun && <div className="notice notice-info">You are signed in as a Viewer. Sign in as an Analyst or Admin to run scenarios.</div>}
      <ErrorNotice error={error} />
      <div className="sim-layout">
        <div className="stack">
          <Panel title="Failure scenarios" aside="Each one uploads a real log file to S3">
            {(catalog?.scenarios || []).map((s) => (
              <div key={s.id} className="scenario" aria-current={current === s.id}>
                <h3>{s.name}</h3>
                <p>{s.summary}</p>
                <div className="expects">{s.expect.map((e) => <span key={e} className="chip">{e}</span>)}</div>
                <button type="button" className="btn" disabled={!canRun || busy} onClick={() => launch({ scenario: s.id }, s.id)}>
                  <Play size={15} /> Run
                </button>
              </div>
            ))}
          </Panel>

          <Panel title="Write your own log line">
            <form className="panel-body composer" onSubmit={(e) => { e.preventDefault(); launch({ custom }, "custom"); }}>
              <label className="field">Service
                <input type="text" required value={custom.service} onChange={(e) => setCustom({ ...custom, service: e.target.value })} />
              </label>
              <label className="field">Level
                <select value={custom.level} onChange={(e) => setCustom({ ...custom, level: e.target.value })}>
                  {LEVELS.map((l) => <option key={l}>{l}</option>)}
                </select>
              </label>
              <label className="field wide">Message
                <input type="text" required value={custom.message} onChange={(e) => setCustom({ ...custom, message: e.target.value })} />
              </label>
              <label className="field">Error code (optional)
                <input type="text" value={custom.error_code} onChange={(e) => setCustom({ ...custom, error_code: e.target.value })} />
              </label>
              <label className="field">Repeat
                <input type="text" inputMode="numeric" value={custom.repeat}
                  onChange={(e) => setCustom({ ...custom, repeat: Number(e.target.value.replace(/\D/g, "")) || 1 })} />
              </label>
              <div className="wide">
                <button type="submit" className="btn btn-primary" disabled={!canRun || busy}><Send size={15} /> Upload log line</button>
              </div>
            </form>
          </Panel>
        </div>

        <div className="stack" ref={traceRef}>
          <Panel title="Follow the file" aside={upload ? (run ? "Processed" : timedOut ? "No response" : "In progress") : ""}>
            <Trace upload={upload} run={run} timedOut={timedOut} />
          </Panel>
          <FileView upload={upload} run={run} />

          <Panel title="Detection rules">
            {(rules?.rules || []).map((r) => (
              <div key={r.id} className="rule-row">
                <strong>{r.name}</strong>
                <Sev level={r.severity} />
                <p>{r.description}</p>
              </div>
            ))}
          </Panel>

          {session.role === "Admin" && (
            <Panel title="Demo data">
              <div className="panel-body" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <span className="muted">Clear all tables before a fresh demonstration.</span>
                <button type="button" className="btn btn-danger" onClick={reset}><RotateCcw size={15} /> Delete all data</button>
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
