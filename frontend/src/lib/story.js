import { MODE } from "../config";
import { fileName, ms, plural } from "./format";

const OUTCOME = { opened: "Opened", reopened: "Reopened", updated: "Updated", duplicate: "Already counted" };
const RANK = { CRITICAL: 0, ERROR: 1, WARNING: 2, INFO: 3 };

const TITLES = {
  upload: "Lands in S3",
  trigger: "Lambda starts",
  validate: "Lines checked",
  store: "Stored",
  detect: "Rules run",
  alert: "Alert",
  failed: "Retried",
};

/**
 * The stages one log file goes through, in the order the 3D model plays them.
 * With no run yet but an upload in flight, returns the same steps with only the first filled in.
 */
export function storySteps(run, upload) {
  if (!run) {
    if (!upload) return [];
    return ["upload", "trigger", "validate", "store", "detect", "alert"].map((key) => ({
      key,
      title: TITLES[key],
      detail: key === "upload"
        ? `${fileName(upload.s3_key)} was uploaded with ${plural(upload.lines.length, "line")}. Waiting for S3 to notify the processor…`
        : "",
    }));
  }

  const steps = [
    {
      key: "upload",
      title: TITLES.upload,
      detail: `${fileName(run.s3_key)} was written to the raw log bucket${run.total_lines != null ? ` with ${plural(run.total_lines, "line")}` : ""}.`,
    },
  ];

  if (run.status === "FAILED") {
    steps.push(
      { key: "trigger", title: TITLES.trigger, tone: "bad", detail: `S3 invoked the processor Lambda, which failed: ${run.error}` },
      { key: "failed", title: TITLES.failed, tone: "bad", detail: "Lambda retries the event twice. If it still fails, the event is parked in the SQS dead-letter queue instead of being lost." },
    );
    return steps;
  }

  const masked = run.pii_redacted ? ` ${plural(run.pii_redacted, "line")} had personal data masked.` : "";
  const detections = (run.detections || []).slice().sort((a, b) => RANK[a.severity] - RANK[b.severity]);
  const top = detections[0];
  const alerts = run.alerts || [];

  steps.push(
    {
      key: "trigger",
      title: TITLES.trigger,
      detail: `The S3 ObjectCreated event invoked the processor Lambda. It ran for ${ms(run.duration_ms)}.`,
    },
    {
      key: "validate",
      title: TITLES.validate,
      tone: run.rejected ? "warn" : undefined,
      detail: (run.rejected
        ? `${plural(run.rejected, "line")} rejected as invalid. The rest of the file carries on.`
        : "Every line was valid JSON with the required fields.") + masked,
    },
    {
      key: "store",
      title: TITLES.store,
      detail: `${plural(run.stored ?? 0, "event")} written to the DynamoDB events table, kept for 7 days.`,
    },
    {
      key: "detect",
      title: TITLES.detect,
      tone: top?.severity,
      detail: top
        ? `${OUTCOME[top.outcome] || top.outcome}${top.escalated ? " and escalated" : ""}: ${top.title}${detections.length > 1 ? ` (and ${detections.length - 1} more)` : ""}.`
        : "No detection rule matched, so no incident changed.",
    },
    alerts.length
      ? { key: "alert", title: "On-call paged", tone: "bad", detail: `SNS published “${alerts[0].subject}”${alerts.length > 1 ? ` and ${alerts.length - 1} more` : ""}.` }
      : { key: "alert", title: "No page", detail: "Nothing critical, so SNS stayed quiet and nobody was paged." },
  );
  return steps;
}

/** The short status lines under each part of the model. `reached` is how many steps have played. */
export function nodeStats(run, upload, reached, session) {
  const at = (key) => {
    if (!run && key !== "upload") return false; // only the upload has happened so far
    const i = storySteps(run, upload).findIndex((s) => s.key === key);
    return i >= 0 && i < reached;
  };
  const alerts = run?.alerts?.length || 0;
  const changed = run?.detections?.length || 0;
  const name = run ? fileName(run.s3_key) : upload ? fileName(upload.s3_key) : null;
  const failed = run?.status === "FAILED";
  const blank = { text: "…" };

  return {
    source: [{ text: run?.scenario || upload?.scenario || (upload ? "custom log line" : "waiting for logs") }],
    s3: [at("upload") ? { text: clip(name, 22) } : { text: name ? "…" : "no files yet" }],
    lambda: [
      !run ? { text: upload && at("upload") ? "waiting for event" : "idle" }
        : failed && at("trigger") ? { text: "failed", hot: true }
          : at("trigger") ? { text: `${run.total_lines ?? 0} lines in ${ms(run.duration_ms)}` } : blank,
    ],
    dynamo: [
      at("store") ? { text: `events +${run.stored ?? 0}` } : { text: "events" },
      at("detect") ? { text: `incidents ${changed} changed`, hot: changed > 0 } : { text: "incidents" },
      at("detect") || (failed && at("failed")) ? { text: failed ? "runs: failure recorded" : "runs: recorded", hot: failed } : { text: "runs" },
    ],
    sns: [at("alert") ? { text: alerts ? `${plural(alerts, "alert")} published` : "nothing to send", hot: alerts > 0 } : { text: "standing by" }],
    oncall: [at("alert") && alerts ? { text: "paged", hot: true } : { text: MODE === "aws" ? "email subscription" : "in-memory topic" }],
    dashboard: [{ text: session ? `${session.role} session` : "" }],
    gateway: [{ text: MODE === "aws" ? "JWT checked at the edge" : "role header (dev only)" }],
    api: [{ text: "roles and statistics" }],
  };
}

const clip = (text = "", max) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
