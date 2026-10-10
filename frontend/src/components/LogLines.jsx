import { useState } from "react";
import { clock, fileName } from "../lib/format";

const LEVEL_SHORT = { CRITICAL: "CRIT", ERROR: "ERROR", WARNING: "WARN", INFO: "INFO" };

/** Stored log events in a terminal-style list; click a line to see every stored field. */
export default function LogLines({ events, emptyText = "No log lines match." }) {
  const [open, setOpen] = useState(null);
  if (!events.length) return <div className="terminal-empty">{emptyText}</div>;
  return events.map((e) => {
    const expanded = open === e.event_id;
    return (
      <div key={e.event_id}>
        <button type="button" className="log-line" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : e.event_id)}>
          <span className="t">{clock(e.timestamp)}</span>
          <span className={`lv-${e.level}`}>{LEVEL_SHORT[e.level]}</span>
          <span className="svc">{e.service}</span>
          <span className="msg">
            {e.message}
            {e.error_code && <span className="code">  [{e.error_code}]</span>}
          </span>
        </button>
        {expanded && (
          <dl className="log-detail">
            <dt>event_id</dt><dd>{e.event_id}</dd>
            <dt>fingerprint</dt><dd>{e.fingerprint}</dd>
            <dt>source</dt><dd>{fileName(e.source_s3_uri)} line {e.line_number}</dd>
            <dt>timestamp</dt><dd>{e.timestamp}</dd>
            {e.endpoint && <><dt>endpoint</dt><dd>{e.endpoint}</dd></>}
            {e.request_id && <><dt>request_id</dt><dd>{e.request_id}</dd></>}
            {e.ip_address && <><dt>ip_address</dt><dd>{e.ip_address} (masked)</dd></>}
            {e.pii_redacted && <><dt>privacy</dt><dd>Personal data in the message was masked before storage</dd></>}
            <dt>expires</dt><dd>{new Date(e.expires_at * 1000).toLocaleDateString()} (DynamoDB TTL)</dd>
          </dl>
        )}
      </div>
    );
  });
}
