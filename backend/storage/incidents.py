"""
Incidents table (cloudlog_incidents).

  PK incident_id ("inc_" + fingerprint) -> one incident per distinct problem
  GSI status-updated_at-index           -> incident queue per status, most recent first

How a detection is applied (see `apply`):
  * an OPEN/ACKNOWLEDGED incident with the same fingerprint gets its occurrence
    counter incremented atomically (DynamoDB ADD) - no duplicate tickets;
  * a RESOLVED incident is reopened ("regression"), keeping its history;
  * `source_files` records which S3 files were already counted, so a Lambda retry
    of the same file is a no-op (exactly-once effect on at-least-once delivery);
  * an ERROR incident reaching ESCALATION_THRESHOLD occurrences becomes CRITICAL.
"""
from dataclasses import dataclass
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.analyzer.detector import Detection
from backend.config import (
    ACKNOWLEDGED,
    ACTIVE_STATUSES,
    CRITICAL,
    ERROR,
    ESCALATION_THRESHOLD,
    INCIDENT_STATUSES,
    OPEN,
    RESOLVED,
    incidents_table,
)
from backend.storage.dynamo import purge, query_pages, table
from backend.util import now_iso

STATUS_INDEX = "status-updated_at-index"


class InvalidTransition(Exception):
    """Raised when e.g. acknowledging an incident that is already resolved."""


@dataclass
class ApplyResult:
    incident: dict[str, Any]
    outcome: str            # opened | reopened | updated | duplicate
    alert: bool             # True when on-call should be paged via SNS
    escalated: bool = False


def _conditional_failed(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _entry(kind: str, detail: str, by: str = "pipeline") -> dict[str, str]:
    return {"at": now_iso(), "type": kind, "detail": detail, "by": by}


class IncidentsStore:
    def __init__(self, table_name: str | None = None, dynamodb: Any | None = None):
        self.table = table(table_name or incidents_table(), dynamodb)

    # ------------------------------------------------------------------ pipeline
    def apply(self, d: Detection, source_uri: str) -> ApplyResult:
        incident_id = f"inc_{d.fingerprint}"
        for _ in range(3):  # retry if a concurrent Lambda wins a race
            updated = self._add_occurrences(incident_id, d, source_uri)
            if updated is not None:
                return self._maybe_escalate(updated, d)

            existing = self.get(incident_id)
            if existing and source_uri in existing.get("source_files", set()):
                return ApplyResult(existing, "duplicate", alert=False)
            opened = self._open(incident_id, d, source_uri, previous=existing)
            if opened is not None:
                return opened
        raise RuntimeError(f"Could not apply detection to {incident_id} after retries")

    def _add_occurrences(self, incident_id: str, d: Detection, uri: str) -> dict[str, Any] | None:
        key = uri.split("/", 3)[-1]
        try:
            response = self.table.update_item(
                Key={"incident_id": incident_id},
                UpdateExpression=(
                    "SET last_seen = :ls, updated_at = :now, timeline = list_append(timeline, :entry) "
                    "ADD occurrences :n, source_files :files"
                ),
                ConditionExpression=(
                    "attribute_exists(incident_id) AND #st IN (:open, :ack) "
                    "AND NOT contains(source_files, :uri)"
                ),
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":ls": d.last_seen, ":now": now_iso(), ":n": d.count, ":files": {uri}, ":uri": uri,
                    ":open": OPEN, ":ack": ACKNOWLEDGED,
                    ":entry": [_entry("occurrence", f"+{d.count} from {key}")],
                },
                ReturnValues="ALL_NEW",
            )
            return response["Attributes"]
        except ClientError as exc:
            if _conditional_failed(exc):
                return None
            raise

    def _maybe_escalate(self, item: dict[str, Any], d: Detection) -> ApplyResult:
        if item["severity"] != ERROR:
            return ApplyResult(item, "updated", alert=False)
        if d.severity == CRITICAL:
            reason = "A critical line was logged for this error"
        elif int(item["occurrences"]) >= ESCALATION_THRESHOLD:
            reason = f"Seen {int(item['occurrences'])} times (threshold {ESCALATION_THRESHOLD})"
        else:
            return ApplyResult(item, "updated", alert=False)
        try:
            response = self.table.update_item(
                Key={"incident_id": item["incident_id"]},
                UpdateExpression="SET severity = :crit, escalated = :t, timeline = list_append(timeline, :e)",
                ConditionExpression="severity = :err",
                ExpressionAttributeValues={
                    ":crit": CRITICAL, ":err": ERROR, ":t": True,
                    ":e": [_entry("escalated", f"Escalated to CRITICAL. {reason}.")],
                },
                ReturnValues="ALL_NEW",
            )
            return ApplyResult(response["Attributes"], "updated", alert=True, escalated=True)
        except ClientError as exc:
            if _conditional_failed(exc):  # someone else escalated first
                return ApplyResult(self.get(item["incident_id"]) or item, "updated", alert=False)
            raise

    def _open(self, incident_id: str, d: Detection, uri: str,
              previous: dict[str, Any] | None) -> ApplyResult | None:
        stamp = now_iso()
        severity, escalated = d.severity, False
        if severity == ERROR and d.count >= ESCALATION_THRESHOLD:
            severity, escalated = CRITICAL, True

        timeline = list(previous.get("timeline", [])) if previous else []
        if previous:
            timeline.append(_entry("reopened", "Problem came back after it was resolved"))
        timeline.append(_entry("opened", f"Rule '{d.rule_id}' matched {d.count} line(s)"))
        if escalated:
            timeline.append(_entry("escalated", f"Escalated to CRITICAL. Seen {d.count} times in one batch."))

        item: dict[str, Any] = {
            "incident_id": incident_id,
            "fingerprint": d.fingerprint,
            "log_fingerprint": d.log_fingerprint or d.fingerprint,
            "status": OPEN,
            "severity": severity,
            "escalated": escalated,
            "rule_id": d.rule_id,
            "category": d.category,
            "service": d.service,
            "title": d.title,
            "occurrences": d.count,
            "first_seen": d.first_seen,
            "last_seen": d.last_seen,
            "created_at": stamp,
            "updated_at": stamp,
            "source_files": {uri},
            "sample_event_ids": d.event_ids,
            "timeline": timeline,
            "alerts_sent": int(previous.get("alerts_sent", 0)) if previous else 0,
            "reopen_count": int(previous.get("reopen_count", 0)) + 1 if previous else 0,
        }
        if d.error_code:
            item["error_code"] = d.error_code
        if d.source_ip:
            item["source_ip"] = d.source_ip
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(incident_id) OR #st = :resolved",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":resolved": RESOLVED},
            )
        except ClientError as exc:
            if _conditional_failed(exc):
                return None
            raise
        return ApplyResult(item, "reopened" if previous else "opened",
                           alert=severity == CRITICAL, escalated=escalated)

    def record_alert(self, incident_id: str, message_id: str) -> None:
        self.table.update_item(
            Key={"incident_id": incident_id},
            UpdateExpression="SET timeline = list_append(timeline, :e) ADD alerts_sent :one",
            ExpressionAttributeValues={
                ":one": 1, ":e": [_entry("alerted", f"SNS alert published (message {message_id})", "sns")],
            },
        )

    # ------------------------------------------------------------------ lifecycle
    def acknowledge(self, incident_id: str, by: str, note: str = "") -> dict[str, Any] | None:
        return self._transition(incident_id, ACKNOWLEDGED, (OPEN,), by, note,
                                "SET acknowledged_at = :now, acknowledged_by = :by")

    def resolve(self, incident_id: str, by: str, note: str = "") -> dict[str, Any] | None:
        return self._transition(incident_id, RESOLVED, ACTIVE_STATUSES, by, note,
                                "SET resolved_at = :now, resolved_by = :by")

    def _transition(self, incident_id: str, target: str, allowed_from, by: str, note: str,
                    set_expr: str) -> dict[str, Any] | None:
        detail = f"Marked {target.lower()}" + (f": {note.strip()}" if note.strip() else "")
        values = {
            ":target": target, ":now": now_iso(), ":by": by,
            ":e": [_entry(target.lower(), detail, by)],
        }
        values.update({f":from{i}": s for i, s in enumerate(allowed_from)})
        try:
            response = self.table.update_item(
                Key={"incident_id": incident_id},
                UpdateExpression=f"{set_expr}, #st = :target, updated_at = :now, "
                                 "timeline = list_append(timeline, :e)",
                ConditionExpression=f"attribute_exists(incident_id) AND #st IN "
                                    f"({', '.join(f':from{i}' for i in range(len(allowed_from)))})",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            return response["Attributes"]
        except ClientError as exc:
            if not _conditional_failed(exc):
                raise
        current = self.get(incident_id)
        if current is None:
            return None
        raise InvalidTransition(f"Incident is {current['status']}; cannot mark it {target.lower()}")

    # ------------------------------------------------------------------ queries
    def get(self, incident_id: str) -> dict[str, Any] | None:
        return self.table.get_item(Key={"incident_id": incident_id}).get("Item")

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        statuses = [status] if status else list(INCIDENT_STATUSES)
        items: list[dict[str, Any]] = []
        for s in statuses:
            items += query_pages(
                self.table, limit, IndexName=STATUS_INDEX,
                KeyConditionExpression=Key("status").eq(s), ScanIndexForward=False,
            )
        items.sort(key=lambda i: i["updated_at"], reverse=True)
        return items[:limit]

    def purge(self) -> int:
        return purge(self.table, ["incident_id"])
