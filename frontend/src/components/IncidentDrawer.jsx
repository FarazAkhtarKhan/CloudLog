import { Check, Eye, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { ago, dateTime } from "../lib/format";
import { useLive, usePoll } from "../lib/hooks";
import LogLines from "./LogLines";
import { useToast } from "../lib/toast";
import { ErrorNotice, Sev, Status } from "./ui";

const RULE_NAMES = {
  "critical-log": "Critical log line",
  "error-log": "Error log line",
  "brute-force": "Brute-force login",
  "warning-burst": "Warning burst",
};

export default function IncidentDrawer({ id, onClose, onChanged }) {
  const { session, live } = useLive();
  const toast = useToast();
  const { data, error, reload } = usePoll(() => api.incident(id), [id], live ? 4000 : null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const canTriage = session.role !== "Viewer";

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function act(action) {
    setBusy(action);
    setActionError(null);
    try {
      await api.triage(id, action, note);
      toast(action === "acknowledge" ? "Incident acknowledged" : "Incident resolved", inc?.title);
      setNote("");
      await reload();
      onChanged?.();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(null);
    }
  }

  const inc = data?.incident;
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <div className="drawer-head">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {inc && <Sev level={inc.severity} />}
            {inc && <Status value={inc.status} />}
            {inc?.escalated && <span className="chip">Escalated</span>}
            {inc?.reopen_count > 0 && <span className="chip">Reopened {inc.reopen_count}×</span>}
            <button type="button" className="btn btn-quiet btn-sm" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
          </div>
          <h2 id="drawer-title">{inc ? inc.title : "Loading incident…"}</h2>
        </div>
        <ErrorNotice error={error} />
        {inc && (
          <>
            <section className="drawer-section">
              <dl className="facts">
                <dt>Service</dt><dd>{inc.service}</dd>
                <dt>Detected by</dt><dd>{RULE_NAMES[inc.rule_id] || inc.rule_id} ({inc.category})</dd>
                {inc.error_code && <><dt>Error code</dt><dd className="mono">{inc.error_code}</dd></>}
                {inc.source_ip && <><dt>Source IP</dt><dd className="mono">{inc.source_ip}</dd></>}
                <dt>Occurrences</dt><dd className="num">{inc.occurrences} across {inc.source_file_count} log file{inc.source_file_count === 1 ? "" : "s"}</dd>
                <dt>First seen</dt><dd>{dateTime(inc.first_seen)}</dd>
                <dt>Last seen</dt><dd>{dateTime(inc.last_seen)} ({ago(inc.last_seen)})</dd>
                <dt>SNS alerts</dt><dd className="num">{inc.alerts_sent}</dd>
                <dt>Incident ID</dt><dd className="mono">{inc.incident_id}</dd>
              </dl>
            </section>

            {inc.status !== "RESOLVED" && (
              <section className="drawer-section triage">
                <h3>Respond</h3>
                {!canTriage && <p className="muted">Viewers can read incidents but not change them.</p>}
                <label className="field">
                  Note for the timeline (optional)
                  <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} disabled={!canTriage}
                    placeholder="What did you find or change?" />
                </label>
                <ErrorNotice error={actionError} />
                <div className="triage-actions">
                  {inc.status === "OPEN" && (
                    <button type="button" className="btn" disabled={!canTriage || busy} onClick={() => act("acknowledge")}>
                      <Eye size={16} /> {busy === "acknowledge" ? "Acknowledging…" : "Acknowledge"}
                    </button>
                  )}
                  <button type="button" className="btn btn-primary" disabled={!canTriage || busy} onClick={() => act("resolve")}>
                    <Check size={16} /> {busy === "resolve" ? "Resolving…" : "Resolve"}
                  </button>
                </div>
              </section>
            )}

            <section className="drawer-section">
              <h3>Timeline</h3>
              <ol className="timeline">
                {inc.timeline.slice().reverse().map((t, i) => (
                  <li key={i} className={`tl-${t.type}`}>
                    <div>{t.detail}</div>
                    <div className="when">{dateTime(t.at)} by {t.by}</div>
                  </li>
                ))}
              </ol>
            </section>

            <section className="drawer-section">
              <h3>Matching log lines</h3>
              <div className="terminal compact">
                <div className="terminal-body" style={{ maxHeight: 320 }}>
                  <LogLines events={data.events} emptyText="The log lines for this incident have expired." />
                </div>
              </div>
            </section>
          </>
        )}
      </aside>
    </>
  );
}
