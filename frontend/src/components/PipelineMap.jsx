import { useEffect, useRef, useState } from "react";
import { MODE } from "../config";
import { fileName, ms } from "../lib/format";

// Edge geometry (viewBox 990 x 290). Top lane = event-driven ingestion, bottom lane = queries.
const EDGES = {
  upload: "M160 85 H205",
  trigger: "M355 85 H400",
  store: "M550 85 H600",
  alert: "M475 46 V24 H895 V46",
  notify: "M895 124 V196",
  request: "M160 235 H205",
  invoke: "M355 235 H400",
  query: "M550 235 H600",
};

const clip = (text, max) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

function Node({ x, y, w = 150, h = 78, kind, name, stats = [], active, alerting }) {
  return (
    <g className={`node${active ? " active" : ""}${alerting ? " alerting" : ""}`} transform={`translate(${x} ${y})`}>
      <rect width={w} height={h} rx="7" />
      <text className="node-kind" x="12" y="20">{kind}</text>
      <text className="node-name" x="12" y="40">{name}</text>
      {stats.map((s, i) => (
        <text key={i} className={`node-stat${s.hot ? " hot" : ""}`} x={s.indent ? 24 : 12} y={60 + i * 18}>{s.text}</text>
      ))}
    </g>
  );
}

/** Animated packet that follows the path of one processed file through the pipeline. */
function Packets({ run }) {
  const first = useRef(null);
  useEffect(() => {
    first.current?.beginElement?.();
  }, []);
  const hops = ["upload", "trigger", "store"];
  if (run.alerts?.length) hops.push("alert", "notify");
  const id = (i) => `pk-${run.run_id}-${i}`;
  return hops.map((edge, i) => (
    <circle key={edge} r="5.5" className={`packet${edge === "alert" || edge === "notify" ? " bad" : ""}`} opacity="0">
      <animateMotion
        id={id(i)}
        ref={i === 0 ? first : undefined}
        dur="0.5s"
        begin={i === 0 ? "indefinite" : `${id(i - 1)}.end`}
        path={EDGES[edge]}
        fill="freeze"
      />
      <set attributeName="opacity" to="1" begin={`${id(i)}.begin`} end={`${id(i)}.end`} />
    </circle>
  ));
}

export default function PipelineMap({ run, session }) {
  const runId = run?.run_id ? `${run.run_id}${run.started_at}` : null;
  const [seenRun, setSeenRun] = useState(null);
  const [fresh, setFresh] = useState(false);
  if (runId !== seenRun) {
    setSeenRun(runId); // a new file arrived: highlight its path
    setFresh(Boolean(runId));
  }
  useEffect(() => {
    if (!fresh) return undefined;
    const t = setTimeout(() => setFresh(false), 4000);
    return () => clearTimeout(t);
  }, [fresh, seenRun]);

  const alerts = run?.alerts?.length || 0;
  const changed = run?.detections?.length || 0;
  const label = MODE === "aws" ? "AWS" : "Emulated";

  return (
    <div className="map-wrap">
      <svg className="map" viewBox="0 0 990 290" role="img"
        aria-label="CloudLog architecture: log files flow from S3 through the processor Lambda into DynamoDB, and critical incidents are published to SNS. The dashboard queries DynamoDB through API Gateway and the API Lambda.">
        <text className="lane" x="10" y="30">Ingestion, event-driven</text>
        <text className="lane" x="10" y="182">Queries, request and response</text>

        {Object.entries(EDGES).map(([name, d]) => (
          <path key={name} d={d}
            className={`edge${["request", "invoke", "query"].includes(name) ? " edge-req" : ""}${fresh && !["request", "invoke", "query"].includes(name) && (alerts || !["alert", "notify"].includes(name)) ? " active" : ""}`} />
        ))}

        <Node x={10} y={46} kind="Log source" name={run?.trigger === "upload" ? "File upload" : "Simulator"}
          stats={[{ text: run?.scenario || "waiting for logs" }]} active={fresh} />
        <Node x={205} y={46} kind={`${label} S3`} name="Raw log bucket"
          stats={[{ text: run ? clip(fileName(run.s3_key), 19) : "no files yet" }]} active={fresh} />
        <Node x={400} y={46} kind={`${label} Lambda`} name="Log processor"
          stats={[{ text: run ? `${run.total_lines ?? 0} lines in ${ms(run.duration_ms)}` : "idle" }]} active={fresh} />
        <Node x={600} y={46} w={170} h={228} kind={`${label} DynamoDB`} name="Tables"
          stats={[
            { text: "cloudlog_events" },
            { text: run ? `+${run.stored ?? 0} stored, ${run.rejected ?? 0} rejected` : "", indent: true },
            { text: "cloudlog_incidents" },
            { text: run ? `${changed} opened or updated` : "", hot: changed > 0, indent: true },
            { text: "cloudlog_pipeline_runs" },
            { text: run ? (run.status === "FAILED" ? "run failed" : "run recorded") : "", hot: run?.status === "FAILED", indent: true },
          ]}
          active={fresh} />
        <Node x={820} y={46} kind={`${label} SNS`} name="Critical alerts"
          stats={[{ text: alerts ? `${alerts} alert${alerts > 1 ? "s" : ""} published` : "nothing to send", hot: alerts > 0 }]}
          active={fresh && alerts > 0} alerting={fresh && alerts > 0} />
        <Node x={820} y={196} kind="Subscribers" name="On-call email"
          stats={[{ text: MODE === "aws" ? "SNS email topic" : "in-memory topic" }]} />

        <Node x={10} y={196} kind="React" name="This dashboard"
          stats={[{ text: session ? `${session.role} session` : "" }]} />
        <Node x={205} y={196} kind={MODE === "aws" ? "API Gateway + Cognito" : "Emulated gateway"} name="HTTP API"
          stats={[{ text: MODE === "aws" ? "JWT checked at the edge" : "role header (dev only)" }]} />
        <Node x={400} y={196} kind={`${label} Lambda`} name="API handler"
          stats={[{ text: "roles and statistics" }]} />

        {run && fresh && <g key={runId}><Packets run={run} /></g>}
      </svg>
    </div>
  );
}
