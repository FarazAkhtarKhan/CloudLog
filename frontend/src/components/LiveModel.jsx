import { Move3d, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PARTS } from "../lib/architecture";
import { nodeStats, storySteps } from "../lib/story";
import PipelineMap from "./PipelineMap";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// Runs that finished longer ago than this are shown at rest instead of being replayed on page load.
const FRESH_MS = 15000;

function Label({ id, stats, onPick }) {
  const part = PARTS[id];
  return (
    <button type="button" className="scene-label" onClick={() => onPick(id)}>
      <span className="scene-label-name">{part.role}</span>
      <span className="scene-label-kind">{part.name}</span>
      {stats.map((s, i) => <span key={i} className={`scene-label-stat${s.hot ? " hot" : ""}`}>{s.text}</span>)}
    </button>
  );
}

/**
 * The pipeline as a 3D model. Each newly processed file is played through it step by step,
 * with a caption saying what is happening. Click any part to read what it does.
 *
 * run:     the pipeline-run record to show (latest, or the simulator's traced file)
 * pending: an upload whose run hasn't been reported yet (simulator only)
 */
export default function LiveModel({ run, pending, session }) {
  const host = useRef(null);
  const [world, setWorld] = useState(null);
  const [flat, setFlat] = useState(false);
  const [reached, setReached] = useState(Infinity);
  const [picked, setPicked] = useState(null);
  const [playing, setPlaying] = useState(false);

  const steps = useMemo(() => storySteps(run, run ? null : pending), [run, pending]);
  const keys = steps.map((s) => s.key);
  const runKey = run ? `${run.run_id}${run.started_at}` : null;
  const pendingUri = !run && pending ? pending.s3_uri : null;

  useEffect(() => {
    let alive = true;
    let made;
    import("../scene/world").then(({ canRender, createWorld }) => {
      if (!alive) return;
      if (!canRender()) return setFlat(true);
      try {
        made = createWorld(host.current, { onPick: setPicked });
        setWorld(made);
      } catch {
        setFlat(true);
      }
    }).catch(() => alive && setFlat(true));
    return () => {
      alive = false;
      made?.dispose();
    };
  }, []);

  // Decide what to play whenever the run (or a pending upload) changes.
  const shown = useRef({ runKey: undefined, pendingUri: null, waiting: null });
  useEffect(() => {
    if (!world) return;
    const memo = shown.current;
    if (pendingUri) {
      if (memo.pendingUri === pendingUri) return;
      memo.pendingUri = pendingUri;
      memo.runKey = null;
      setReached(0);
      setPlaying(true);
      memo.waiting = reducedMotion() ? Promise.resolve(world.settle()) : world.pending(pending.lines.length);
      memo.waiting.then((done) => done !== false && setReached(1));
      return;
    }
    if (memo.runKey === runKey) return;
    memo.runKey = runKey;
    const continuing = run && memo.pendingUri === run.s3_uri;
    const fresh = run && Date.now() - new Date(run.finished_at || run.started_at).getTime() < FRESH_MS;
    if (!run || reducedMotion() || (!continuing && !fresh)) {
      world.settle();
      memo.pendingUri = null;
      setReached(Infinity);
      setPlaying(false);
      return;
    }
    const waiting = continuing ? memo.waiting : null;
    memo.pendingUri = null;
    setPlaying(true);
    Promise.resolve(waiting).then(() => {
      if (memo.runKey !== runKey) return;
      world.play(run, keys, { from: continuing ? 1 : 0, onStep: setReached }).then((done) => done && setPlaying(false));
    });
  }, [world, runKey, pendingUri]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!picked) return undefined;
    const onKey = (e) => e.key === "Escape" && setPicked(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [picked]);

  if (flat) return <div className="map-wrap"><PipelineMap run={run} session={session} /></div>;

  function replay() {
    if (!run || !world) return;
    setPlaying(true);
    world.play(run, keys, { onStep: setReached }).then((done) => done && setPlaying(false));
  }

  const stats = nodeStats(run, run ? null : pending, reached, session);
  const part = picked && PARTS[picked];
  // While playing, say what is happening now; afterwards, sum up how it ended.
  const caption = playing
    ? (steps[reached]?.detail || steps[0]?.detail)
    : steps.filter((s) => ["detect", "alert", "failed"].includes(s.key)).map((s) => s.detail).join(" ");

  return (
    <div className="model">
      <div className="model-stage">
        <div ref={host} className="model-host" role="img"
          aria-label="3D model of CloudLog. Log files flow from S3 through the processor Lambda into DynamoDB, and critical incidents are published to SNS, which pages on-call. The dashboard reads data through the HTTP API and the API Lambda." />
        {world && Object.entries(world.anchors).map(([id, el]) => createPortal(<Label id={id} stats={stats[id]} onPick={setPicked} />, el, id))}
        <div className="model-tools">
          <span className="model-hint"><Move3d size={14} aria-hidden="true" />Drag to turn, click a part to learn what it does</span>
          <button type="button" className="btn btn-sm model-reset" onClick={() => world?.resetView()} disabled={!world}>Reset view</button>
        </div>
        {part && (
          <div className="model-card" role="dialog" aria-label={part.role}>
            <div className="model-card-head">
              <div>
                <strong>{part.role}</strong>
                <span>{part.name}</span>
              </div>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => setPicked(null)} aria-label="Close"><X size={16} /></button>
            </div>
            <p>{part.text}</p>
          </div>
        )}
      </div>

      <div className="story">
        {steps.length > 0 ? (
          <>
            <ol className="story-steps">
              {steps.map((s, i) => {
                const state = i < reached ? "done" : playing && i === reached ? "now" : "todo";
                return (
                  <li key={s.key} className={`story-step ${state}${s.tone ? ` tone-${s.tone}` : ""}`}>
                    <span className="story-num num">{i + 1}</span>
                    <span>{s.title}</span>
                  </li>
                );
              })}
            </ol>
            <div className="story-caption">
              <p aria-live="polite">{caption}</p>
              <button type="button" className="btn btn-sm" onClick={replay} disabled={!run || !world || playing}>
                <RotateCcw size={14} /> Replay
              </button>
            </div>
          </>
        ) : (
          <div className="story-caption">
            <p>Waiting for the first log file. Run a scenario in the <a href="#/simulator">simulator</a> and watch it travel through the model.</p>
          </div>
        )}
      </div>
    </div>
  );
}
