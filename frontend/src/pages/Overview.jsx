import LiveModel from "../components/LiveModel";
import SignalChart from "../components/SignalChart";
import { Empty, ErrorNotice, Panel, Sev } from "../components/ui";
import { ago, minutes, number, plural } from "../lib/format";
import { useLive } from "../lib/hooks";

function Vital({ value, label, alarm }) {
  return (
    <div className="vital">
      <div className={`vital-value${alarm ? " alarm" : ""}`}>{value}</div>
      <div className="vital-label">{label}</div>
    </div>
  );
}

function HealthSpark({ row }) {
  const total = row.total || 1;
  return (
    <span className="spark" aria-hidden="true">
      {["CRITICAL", "ERROR", "WARNING", "INFO"].map((l) => (
        <i key={l} className={`sw-${l}`} style={{ width: `${(row[l] / total) * 100}%` }} />
      ))}
    </span>
  );
}

export default function Overview({ onOpenIncident }) {
  const { overview, overviewError, latestRun, session, activeIncidents } = useLive();
  const o = overview;
  const inc = o?.incidents;

  return (
    <div className="stack">
      <ErrorNotice error={overviewError} />
      <Panel
        title="Pipeline"
        aside={latestRun ? `Last file processed ${ago(latestRun.finished_at)}` : "Run a simulation to send the first log file"}
      >
        <LiveModel run={latestRun} session={session} />
      </Panel>

      <div className="grid grid-2-1">
        <Panel title="Log volume, last 60 minutes" aside={o ? `${number(o.totals.events)} lines in 24 h` : ""}>
          <div className="panel-body">
            <SignalChart timeline={o?.timeline || []} />
          </div>
        </Panel>
        <Panel title="Right now">
          <div className="vitals">
            <Vital value={inc ? inc.open + inc.acknowledged : "—"} label="Active incidents" alarm={inc?.critical_active > 0} />
            <Vital value={inc ? inc.critical_active : "—"} label="Critical and unresolved" alarm={inc?.critical_active > 0} />
            <Vital value={o ? `${o.totals.error_rate}%` : "—"} label="Error rate, 24 h" />
            <Vital value={o ? number(o.totals.events) : "—"} label="Log lines, 24 h" />
            <Vital value={minutes(inc?.mtta_minutes)} label="Mean time to acknowledge" />
            <Vital value={minutes(inc?.mttr_minutes)} label="Mean time to resolve" />
          </div>
        </Panel>
      </div>

      <div className="grid grid-1-1">
        <Panel title="Needs attention" aside={<a href="#/incidents">All incidents</a>}>
          {activeIncidents.length === 0 ? (
            <Empty title="Nothing needs attention">Run the database outage scenario to see detection at work.</Empty>
          ) : (
            activeIncidents.slice(0, 6).map((i) => (
              <a key={i.incident_id} className="incident-line" href={`#/incidents/${i.incident_id}`}
                onClick={(e) => { e.preventDefault(); onOpenIncident(i.incident_id); }}>
                <span className={`bar bar-${i.severity}`} />
                <span style={{ minWidth: 0 }}>
                  <div className="cell-title">{i.title}</div>
                  <div className="cell-sub">{i.service}, {plural(i.occurrences, "occurrence")}, last {ago(i.last_seen)}</div>
                </span>
                <Sev level={i.severity} />
              </a>
            ))
          )}
        </Panel>

        <Panel title="Service health" aside="From active incidents and 24 h of logs">
          {!o?.services.length ? (
            <Empty title="No services yet">Services appear as soon as their first log line is stored.</Empty>
          ) : (
            o.services.map((s) => (
              <div key={s.service} className="health-row">
                <span className={`dot dot-${s.status}`} title={s.status} />
                <span style={{ minWidth: 0 }}>
                  <a href={`#/logs?service=${encodeURIComponent(s.service)}`}>{s.service}</a>
                  <span className="cell-sub">
                    {"  "}{s.status === "healthy" ? "healthy" : `${s.status}, ${s.active_incidents} active`}
                  </span>
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="cell-sub num">{s.total} lines</span>
                  <HealthSpark row={s} />
                </span>
              </div>
            ))
          )}
          {o?.top_errors.length > 0 && (
            <div className="panel-body" style={{ paddingTop: 12, borderTop: "1px solid var(--rule-soft)" }}>
              <div className="cell-sub" style={{ marginBottom: 6 }}>Most frequent error codes</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {o.top_errors.map((e) => (
                  <span key={`${e.error_code}-${e.service}`} className="chip mono">{e.error_code} ×{e.count}</span>
                ))}
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
