import { Activity, FlaskConical, LayoutDashboard, LogOut, ScrollText, Siren, Workflow } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import IncidentDrawer from "./components/IncidentDrawer";
import { ToastProvider } from "./components/Toasts";
import { useToast } from "./lib/toast";
import { Switch } from "./components/ui";
import { AWS_REGION, MODE, POLL_MS } from "./config";
import { api } from "./lib/api";
import { currentSession, signOut } from "./lib/auth";
import { fileName, plural } from "./lib/format";
import { LiveContext, usePoll, useTick } from "./lib/hooks";
import Incidents from "./pages/Incidents";
import Login from "./pages/Login";
import Logs from "./pages/Logs";
import Overview from "./pages/Overview";
import Pipeline from "./pages/Pipeline";
import Simulator from "./pages/Simulator";

const PAGES = {
  overview: { label: "Overview", icon: LayoutDashboard, title: "Overview", blurb: "What the pipeline is doing and what needs attention." },
  incidents: { label: "Incidents", icon: Siren, title: "Incidents", blurb: "Problems found by the detection rules. Repeats of the same error are grouped into one incident." },
  logs: { label: "Logs", icon: ScrollText, title: "Logs", blurb: "Every stored log line, newest first, straight from DynamoDB." },
  pipeline: { label: "Pipeline", icon: Workflow, title: "Pipeline", blurb: "How a log file moves through the cloud services, and a record of every file processed." },
  simulator: { label: "Simulator", icon: FlaskConical, title: "Simulator", blurb: "Cause a failure on purpose and watch CloudLog detect it." },
};

function parseHash() {
  const [path, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  const [page, id] = path.split("/");
  return { page: PAGES[page] ? page : "overview", id, params: new URLSearchParams(query) };
}

function useHashRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const onChange = () => setRoute(parseHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function Console({ session, onSignOut }) {
  const route = useHashRoute();
  const toast = useToast();
  const [live, setLive] = useState(true);
  useTick(5000);

  const interval = live ? POLL_MS : null;
  const overview = usePoll(() => api.overview(), [], interval);
  const runs = usePoll(() => api.runs(20), [], interval);
  const incidents = usePoll(() => api.incidents(), [], interval);

  const refresh = useCallback(() => {
    overview.reload();
    runs.reload();
    incidents.reload();
  }, [overview.reload, runs.reload, incidents.reload]); // eslint-disable-line react-hooks/exhaustive-deps

  // Announce each newly processed file once.
  const runList = runs.data?.runs || [];
  const latestRun = runList[0] || null;
  const seen = useRef(null);
  useEffect(() => {
    if (!latestRun) return;
    const key = latestRun.run_key || latestRun.run_id;
    if (seen.current && seen.current !== key) {
      const d = latestRun.detections?.length || 0;
      const a = latestRun.alerts?.length || 0;
      toast(
        `Processed ${fileName(latestRun.s3_key)}`,
        `${latestRun.stored} stored, ${latestRun.rejected} rejected, ${plural(d, "incident")} changed${a ? `, ${plural(a, "SNS alert")}` : ""}`,
        a ? "bad" : "ok",
      );
      overview.reload();
      incidents.reload();
    }
    seen.current = key;
  }, [latestRun, toast]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeIncidents = useMemo(
    () => (incidents.data?.incidents || [])
      .filter((i) => i.status !== "RESOLVED")
      .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "CRITICAL" ? -1 : 1)),
    [incidents.data],
  );

  // The open incident lives in the URL (#/incidents/inc_x or ?incident=inc_x) so links can be shared.
  const drawerId = (route.page === "incidents" && route.id) || route.params.get("incident");
  const openIncident = (id) => {
    window.location.hash = route.page === "incidents" ? `#/incidents/${id}` : `#/${route.page}?incident=${id}`;
  };
  const closeDrawer = () => {
    window.location.hash = `#/${route.page}`;
  };

  const context = {
    live, session, refresh,
    overview: overview.data, overviewError: overview.error,
    runs: runList, runsError: runs.error, latestRun, activeIncidents,
  };
  const page = PAGES[route.page];

  return (
    <LiveContext.Provider value={context}>
      <div className="shell">
        <nav className="rail" aria-label="Main">
          <a className="wordmark" href="#/overview">
            <img src="/favicon.svg" width="26" height="26" alt="" />
            <span className="wordmark-name">CloudLog</span>
          </a>
          <div className="nav">
            {Object.entries(PAGES).map(([key, p]) => (
              <a key={key} href={`#/${key}`} aria-current={route.page === key ? "page" : undefined} title={p.label}>
                <p.icon size={18} aria-hidden="true" />
                <span className="label">{p.label}</span>
                {key === "incidents" && activeIncidents.length > 0 && <span className="nav-count num">{activeIncidents.length}</span>}
              </a>
            ))}
          </div>
          <div className="rail-foot">
            <span className="env-line"><span className={`dot ${live ? "dot-live" : "dot-paused"}`} />{live ? "Updating every 4 s" : "Updates paused"}</span>
            <span className="env-line"><Activity size={14} />{MODE === "aws" ? `AWS ${AWS_REGION}` : "Offline emulator"}</span>
          </div>
        </nav>

        <main className="main">
          <header className="topbar">
            <div>
              <h1>{page.title}</h1>
              <p>{page.blurb}</p>
            </div>
            <div className="topbar-actions">
              <Switch checked={live} onChange={setLive}>Live</Switch>
              <span className="user-chip">
                {session.email}
                <span className="role-tag">{session.role}</span>
              </span>
              <button type="button" className="btn btn-quiet btn-sm" onClick={onSignOut} title="Sign out">
                <LogOut size={16} /><span className="visually-hidden">Sign out</span>
              </button>
            </div>
          </header>

          {route.page === "overview" && <Overview onOpenIncident={openIncident} />}
          {route.page === "incidents" && <Incidents selectedId={drawerId} onOpenIncident={openIncident} />}
          {route.page === "logs" && <Logs key={route.params.get("service") || ""} initialService={route.params.get("service") || ""} />}
          {route.page === "pipeline" && <Pipeline />}
          {route.page === "simulator" && <Simulator />}
        </main>
      </div>
      {drawerId && <IncidentDrawer key={drawerId} id={drawerId} onClose={closeDrawer} onChanged={refresh} />}
    </LiveContext.Provider>
  );
}

export default function App() {
  const [session, setSession] = useState(currentSession);
  return (
    <ToastProvider>
      {session
        ? <Console session={session} onSignOut={() => { signOut(); setSession(null); }} />
        : <Login onSignedIn={setSession} />}
    </ToastProvider>
  );
}
