import { useEffect, useState } from "react";
import LogLines from "../components/LogLines";
import { ErrorNotice, Segmented, Switch } from "../components/ui";
import { LEVELS } from "../config";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/hooks";

function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function Logs({ initialService = "" }) {
  const { live, overview } = useLive();
  const [level, setLevel] = useState("");
  const [service, setService] = useState(initialService);
  const [search, setSearch] = useState("");
  const [tail, setTail] = useState(true);
  const q = useDebounced(search.trim());

  const { data, error, loading } = usePoll(
    () => api.events({ level, service, q, limit: 150 }),
    [level, service, q],
    live && tail ? 3000 : null,
  );
  const services = overview?.services.map((s) => s.service).sort() || [];
  const events = data?.events || [];

  return (
    <div className="stack">
      <div className="toolbar">
        <input className="search" type="search" placeholder="Search messages or error codes" value={search}
          onChange={(e) => setSearch(e.target.value)} aria-label="Search log lines" />
        <select value={service} onChange={(e) => setService(e.target.value)} aria-label="Service">
          <option value="">All services</option>
          {services.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <Segmented label="Level" value={level} onChange={setLevel}
          options={[{ value: "", label: "All" }, ...LEVELS.map((l) => ({ value: l, label: l[0] + l.slice(1).toLowerCase() }))]} />
        <span className="spacer" />
        <Switch checked={tail} onChange={setTail}>Follow new lines</Switch>
      </div>
      <ErrorNotice error={error} />
      <div className="terminal">
        <div className="terminal-head">
          <span>cloudlog_events{service ? ` / ${service}` : " / feed-index"}</span>
          <span>{loading ? "querying DynamoDB…" : `${events.length} newest lines`}</span>
        </div>
        <div className="terminal-body">
          <LogLines events={events} emptyText="No log lines match these filters. Run a scenario from the simulator." />
        </div>
      </div>
    </div>
  );
}
