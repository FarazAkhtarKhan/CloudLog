"""
Lambda #1 - Log processor (triggered by S3 ObjectCreated on *.jsonl).

  S3 file -> parse & validate -> store events -> run detection rules
          -> open/update incidents -> SNS alert for critical ones
          -> write a pipeline-run record (what happened, how long it took)

A failure re-raises so Lambda's async retry and the SQS dead-letter queue take over;
deterministic IDs make the retry safe.
"""
import hashlib
import logging
import time
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from urllib.parse import unquote_plus

import boto3

from backend.alerts.sns import AlertPublisher, alert_subject
from backend.analyzer.detector import detect
from backend.analyzer.parser import parse_lines
from backend.config import SEVERITIES, SIMULATION_PREFIX, aws_region
from backend.storage.events import EventsStore
from backend.storage.incidents import IncidentsStore
from backend.storage.runs import RunsStore
from backend.util import now_iso

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _lines(body) -> Iterator[str]:
    for raw in body.iter_lines():
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError:
            yield "\x00 not utf-8"  # rejected by the parser as INVALID_JSON, keeps line numbers aligned


class Processor:
    def __init__(self, s3=None, events: EventsStore | None = None,
                 incidents: IncidentsStore | None = None, runs: RunsStore | None = None,
                 alerts: AlertPublisher | None = None):
        self.s3 = s3 or boto3.client("s3", region_name=aws_region())
        self.events = events or EventsStore()
        self.incidents = incidents or IncidentsStore()
        self.runs = runs or RunsStore()
        self.alerts = alerts or AlertPublisher()

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        runs = []
        for record in event.get("Records", []):
            s3 = record.get("s3", {})
            bucket, key = s3.get("bucket", {}).get("name"), s3.get("object", {}).get("key")
            if not bucket or not key:
                continue
            key = unquote_plus(key)  # S3 URL-encodes keys in notifications
            if key.endswith(".jsonl"):
                runs.append(self.process_file(bucket, key))
        return {"processed_files": len(runs), "runs": runs}

    def process_file(self, bucket: str, key: str) -> dict[str, Any]:
        uri = f"s3://{bucket}/{key}"
        started_at, t0 = now_iso(), time.perf_counter()
        run: dict[str, Any] = {
            "run_id": "run_" + hashlib.sha256(uri.encode()).hexdigest()[:12],
            "s3_uri": uri,
            "s3_key": key,
            "started_at": started_at,
            "trigger": "simulator" if key.startswith(SIMULATION_PREFIX) else "upload",
        }
        try:
            stages: dict[str, float] = {}
            t = time.perf_counter()
            obj = self.s3.get_object(Bucket=bucket, Key=key)
            meta = obj.get("Metadata", {})
            run.update(size_bytes=int(obj.get("ContentLength", 0)),
                       scenario=meta.get("scenario"), triggered_by=meta.get("triggered-by"))
            stages["s3_read_ms"] = _ms_since(t)

            t = time.perf_counter()
            batch = parse_lines(_lines(obj["Body"]), bucket, key)
            stages["parse_ms"] = _ms_since(t)

            t = time.perf_counter()
            self.events.save(batch.events)
            stages["store_ms"] = _ms_since(t)

            t = time.perf_counter()
            detections, alerts = [], []
            pending_alerts = []
            for d in detect(batch.events):
                result = self.incidents.apply(d, uri)
                detections.append({
                    "incident_id": result.incident["incident_id"],
                    "rule_id": d.rule_id,
                    "severity": result.incident["severity"],
                    "title": d.title,
                    "count": d.count,
                    "outcome": result.outcome,
                    "escalated": result.escalated,
                })
                if result.alert:
                    pending_alerts.append(result)
            stages["detect_ms"] = _ms_since(t)

            t = time.perf_counter()
            for result in pending_alerts:
                reason = ("escalated after repeated occurrences" if result.escalated
                          else "problem came back" if result.outcome == "reopened"
                          else "new critical problem")
                message_id = self.alerts.publish(result.incident, reason)
                if message_id:
                    self.incidents.record_alert(result.incident["incident_id"], message_id)
                    alerts.append({"incident_id": result.incident["incident_id"], "message_id": message_id,
                                   "subject": alert_subject(result.incident)})
            stages["alert_ms"] = _ms_since(t)

            levels = {lvl: 0 for lvl in SEVERITIES}
            for e in batch.events:
                levels[e.level] += 1
            run.update(
                status="SUCCESS",
                total_lines=batch.total_lines,
                stored=len(batch.events),
                rejected=len(batch.rejections),
                rejections=[r.__dict__ for r in batch.rejections[:10]],
                pii_redacted=sum(1 for e in batch.events if e.pii_redacted),
                levels=levels,
                detections=detections,
                alerts=alerts,
                stages=stages,
            )
            logger.info("Processed %s: %d stored, %d rejected, %d detections, %d alerts",
                        uri, len(batch.events), len(batch.rejections), len(detections), len(alerts))
            return self._finish(run, t0)
        except Exception as exc:
            logger.exception("Processing failed for %s", uri)
            run.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
            self._finish(run, t0)
            raise

    def _finish(self, run: dict[str, Any], t0: float) -> dict[str, Any]:
        run["finished_at"] = now_iso()
        run["duration_ms"] = _ms_since(t0)
        try:
            self.runs.save(_dynamo_safe(run))
        except Exception:  # run history is diagnostics; never let it mask the real outcome
            logger.exception("Could not save pipeline run %s", run["run_id"])
        return run


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _dynamo_safe(run: dict[str, Any]) -> dict[str, Any]:
    """DynamoDB rejects Python floats and None values; convert/drop them."""
    def convert(v):
        if isinstance(v, float):
            return Decimal(str(v))
        if isinstance(v, dict):
            return {k: convert(x) for k, x in v.items() if x is not None}
        if isinstance(v, list):
            return [convert(x) for x in v]
        return v
    return convert(run)


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return Processor().handle(event)
