import { useState } from "react";
import { Empty, ErrorNotice, Panel, Segmented, Sev, Status } from "../components/ui";
import { api } from "../lib/api";
import { ago } from "../lib/format";
import { useLive, usePoll } from "../lib/hooks";

const RULE_SHORT = {
  "critical-log": "Critical line",
  "error-log": "Error line",
  "brute-force": "Brute force",
  "warning-burst": "Warning burst",
};

const FILTERS = [
  { value: "active", label: "Active", test: (i) => i.status !== "RESOLVED" },
  { value: "OPEN", label: "Open", test: (i) => i.status === "OPEN" },
  { value: "ACKNOWLEDGED", label: "Acknowledged", test: (i) => i.status === "ACKNOWLEDGED" },
  { value: "RESOLVED", label: "Resolved", test: (i) => i.status === "RESOLVED" },
  { value: "all", label: "All", test: () => true },
];

export default function Incidents({ selectedId, onOpenIncident }) {
  const { live } = useLive();
  const [filter, setFilter] = useState("active");
  const { data, error } = usePoll(() => api.incidents(), [], live ? 4000 : null);
  const all = data?.incidents || [];
  const rows = all.filter(FILTERS.find((f) => f.value === filter).test);

  return (
    <div className="stack">
      <ErrorNotice error={error} />
      <div className="toolbar">
        <Segmented label="Filter incidents by status" value={filter} onChange={setFilter}
          options={FILTERS.map((f) => ({ ...f, count: all.filter(f.test).length }))} />
      </div>
      <Panel>
        {rows.length === 0 ? (
          <Empty title={filter === "active" ? "No active incidents" : "No incidents here"}>
            {filter === "active" ? "Everything detected so far has been resolved." : "Try another filter."}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Problem</th>
                  <th>Detected by</th>
                  <th className="right">Seen</th>
                  <th>Last seen</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((i) => (
                  <tr key={i.incident_id} className={`clickable${selectedId === i.incident_id ? " selected" : ""}`}
                    onClick={() => onOpenIncident(i.incident_id)}>
                    <td><Sev level={i.severity} /></td>
                    <td>
                      <button type="button" className="cell-title link-button"
                        onClick={(e) => { e.stopPropagation(); onOpenIncident(i.incident_id); }}>
                        {i.title}
                      </button>
                      <div className="cell-sub">
                        {i.service}
                        {i.error_code && <span className="mono">  {i.error_code}</span>}
                        {i.escalated && "  escalated"}
                      </div>
                    </td>
                    <td className="cell-sub">{RULE_SHORT[i.rule_id] || i.rule_id}</td>
                    <td className="right num">{i.occurrences}×</td>
                    <td className="cell-sub">{ago(i.last_seen)}</td>
                    <td><Status value={i.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
