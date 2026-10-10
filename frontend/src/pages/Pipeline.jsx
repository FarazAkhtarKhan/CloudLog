import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import PipelineMap from "../components/PipelineMap";
import { Empty, ErrorNotice, Panel, Sev, Status } from "../components/ui";
import { MODE } from "../config";
import { clock, fileName, ms } from "../lib/format";
import { useLive } from "../lib/hooks";

const STAGES = [
  { key: "s3_read_ms", label: "Read from S3", color: "#7f8ea1" },
  { key: "parse_ms", label: "Validate and mask", color: "#23708d" },
  { key: "store_ms", label: "Write events", color: "#1b2430" },
  { key: "detect_ms", label: "Detect and upsert incidents", color: "#c4511c" },
  { key: "alert_ms", label: "Publish SNS", color: "#c8102e" },
];

const COMPONENTS = [
  { name: "Amazon S3", role: "Raw log bucket", text: "Services drop JSON Lines files here. Every new .jsonl object emits an ObjectCreated event. Encrypted at rest, public access blocked." },
  { name: "AWS Lambda", role: "Log processor", text: "Runs once per file, scales out automatically per upload. Validates each line, masks personal data, stores events and applies the detection rules." },
  { name: "Amazon DynamoDB", role: "Three on-demand tables", text: "Events (partitioned by service, plus a per-day feed index), incidents (indexed by status) and pipeline runs. TTL deletes old data for free." },
  { name: "Amazon SNS", role: "Critical alert topic", text: "Fans one message out to every subscriber (email, SMS, HTTPS) when an incident is critical, escalated or comes back." },
  { name: "API Gateway + Cognito", role: "HTTP API with JWT authorizer", text: "Verifies the sign-in token at the edge before any Lambda runs. Cognito groups map to Admin, Analyst and Viewer roles." },
  { name: "AWS Lambda", role: "API handler", text: "Serves the dashboard, enforces role permissions and computes the statistics with a map, shuffle and reduce pass." },
  { name: "Amazon SQS", role: "Dead-letter queue", text: "If the processor still fails after Lambda's automatic retries, the S3 event is parked here instead of being lost." },
  { name: "Amazon CloudWatch", role: "Logs and alarms", text: "Captures both functions' logs and raises an alarm to SNS when the processor reports errors or the DLQ fills up." },
];

function RunDetail({ run }) {
  const total = STAGES.reduce((s, st) => s + (run.stages?.[st.key] || 0), 0) || 1;
  return (
    <tr className="run-detail">
      <td colSpan={8}>
        {run.status === "FAILED" && <p className="notice notice-error">{run.error}</p>}
        {run.stages && (
          <>
            <div className="stage-bar" aria-hidden="true">
              {STAGES.map((st) => (
                <i key={st.key} style={{ width: `${((run.stages[st.key] || 0) / total) * 100}%`, background: st.color }} />
              ))}
            </div>
            <div className="stage-legend">
              {STAGES.map((st) => (
                <span key={st.key}><i style={{ background: st.color }} />{st.label} {ms(run.stages[st.key])}</span>
              ))}
            </div>
          </>
        )}
        <div className="cols">
          <div>
            <h4>File</h4>
            <ul>
              <li className="mono">{run.s3_uri}</li>
              <li>{run.size_bytes} bytes, {run.total_lines} lines</li>
              {run.triggered_by && <li>Uploaded by {run.triggered_by}</li>}
              {run.pii_redacted > 0 && <li>{run.pii_redacted} lines had personal data masked</li>}
            </ul>
          </div>
          <div>
            <h4>Rejected lines</h4>
            <ul>
              {run.rejections?.length ? run.rejections.map((r) => (
                <li key={r.line_number}>Line {r.line_number}: <span className="mono">{r.reason}</span> {r.detail}</li>
              )) : <li className="muted">None</li>}
            </ul>
          </div>
          <div>
            <h4>Incidents</h4>
            <ul>
              {run.detections?.length ? run.detections.map((d) => (
                <li key={d.incident_id}><Sev level={d.severity} /> {d.outcome} <a href={`#/incidents/${d.incident_id}`}>{d.title.slice(0, 60)}</a></li>
              )) : <li className="muted">No rule matched</li>}
            </ul>
          </div>
          <div>
            <h4>SNS alerts</h4>
            <ul>
              {run.alerts?.length ? run.alerts.map((a) => (
                <li key={a.message_id}>{a.subject}<div className="cell-sub mono">{a.message_id}</div></li>
              )) : <li className="muted">None sent</li>}
            </ul>
          </div>
        </div>
      </td>
    </tr>
  );
}

export default function Pipeline() {
  const { runs, runsError, latestRun, session } = useLive();
  const [open, setOpen] = useState(null);

  return (
    <div className="stack">
      <Panel title="Architecture" aside={MODE === "aws" ? "Live AWS deployment" : "Running in the offline emulator"}>
        <PipelineMap run={latestRun} session={session} />
      </Panel>

      <Panel title="Processed files" aside="One row per Lambda invocation, newest first">
        <ErrorNotice error={runsError} />
        {!runs.length ? (
          <Empty title="No files processed yet">Run a scenario from the simulator and it will appear here within a second or two.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th aria-label="Expand" />
                  <th>Started</th>
                  <th>File</th>
                  <th className="right">Stored</th>
                  <th className="right">Rejected</th>
                  <th className="right">Incidents</th>
                  <th className="right">Alerts</th>
                  <th className="right">Lambda time</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const key = r.run_key || r.run_id;
                  const expanded = open === key;
                  return (
                    <Fragment key={key}>
                      <tr className="clickable" onClick={() => setOpen(expanded ? null : key)} aria-expanded={expanded}>
                        <td>{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</td>
                        <td className="num">{clock(r.started_at)}</td>
                        <td>
                          <div className="mono">{fileName(r.s3_key)}</div>
                          <div className="cell-sub">{r.trigger === "simulator" ? `simulator, ${r.scenario}` : "direct upload"} {r.status === "FAILED" && <Status value="FAILED" />}</div>
                        </td>
                        <td className="right num">{r.stored ?? "—"}</td>
                        <td className="right num">{r.rejected ?? "—"}</td>
                        <td className="right num">{r.detections?.length ?? 0}</td>
                        <td className="right num">{r.alerts?.length ?? 0}</td>
                        <td className="right num">{ms(r.duration_ms)}</td>
                      </tr>
                      {expanded && <RunDetail run={r} />}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="What each component does">
        <div className="component-list">
          {COMPONENTS.map((c) => (
            <div key={c.role} className="component">
              <h3>{c.role}</h3>
              <div className="svc">{c.name}</div>
              <p>{c.text}</p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
