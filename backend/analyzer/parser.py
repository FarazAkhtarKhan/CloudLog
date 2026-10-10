"""
Pure-Python log parser (no AWS calls).

Each JSONL line is validated against the log contract, normalised, masked for
PII and given two identifiers:

* event_id    - SHA-256 of (bucket, key, line). Re-processing the same file after a
                Lambda retry yields the same IDs, so DynamoDB writes are idempotent.
* fingerprint - SHA-256 of (service, error code or message "shape"). Lines that
                describe the same problem share a fingerprint, so they group into
                one incident instead of flooding the queue.
"""
import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime

from backend.analyzer.models import Batch, LogEvent, Rejection
from backend.analyzer.privacy import redact
from backend.config import SEVERITIES

REQUIRED_FIELDS = ("timestamp", "service", "level", "message")

# Variable parts of a message that should not split a fingerprint
_VOLATILE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUIDs
    r"|\b[0-9a-f]{12,}\b"                                            # hex ids
    r"|\d+(?:\.\d+)*",                                               # numbers, IPs
    re.IGNORECASE,
)


def _sha(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def event_id_for(bucket: str, key: str, line_number: int) -> str:
    return "evt_" + _sha(f"{bucket}:{key}:{line_number}")


def message_shape(message: str) -> str:
    """'Timeout after 5012ms on 10.0.0.4' -> 'timeout after #ms on #'."""
    return _VOLATILE.sub("#", message.lower()).strip()


def fingerprint_for(service: str, error_code: str | None, message: str) -> str:
    basis = error_code.upper() if error_code else message_shape(message)
    return _sha(f"{service}|{basis}", 12)


def normalise_timestamp(value: object) -> str | None:
    """Parse ISO-8601 and return UTC 'YYYY-MM-DDTHH:MM:SS.mmmZ' (sortable as a string)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(payload: dict, name: str) -> str | None:
    value = payload.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_line(raw: str, bucket: str, key: str, line_number: int) -> LogEvent | Rejection:
    """Validate one line. Returns a LogEvent, or a Rejection explaining why not."""
    def reject(reason: str, detail: str) -> Rejection:
        return Rejection(line_number=line_number, reason=reason, detail=detail)

    if not raw or not raw.strip():
        return reject("EMPTY_LINE", "Line is blank")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return reject("INVALID_JSON", f"{exc.msg} at column {exc.colno}")
    if not isinstance(payload, dict):
        return reject("INVALID_JSON", "Line is valid JSON but not an object")

    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        return reject("MISSING_FIELDS", "Missing " + ", ".join(missing))

    service, message = _text(payload, "service"), _text(payload, "message")
    if not service:
        return reject("MISSING_FIELDS", "'service' is empty")
    if not message:
        return reject("MISSING_FIELDS", "'message' is empty")

    level = str(payload.get("level", "")).strip().upper()
    if level not in SEVERITIES:
        return reject("INVALID_LEVEL", f"'{payload.get('level')}' is not one of {', '.join(SEVERITIES)}")

    timestamp = normalise_timestamp(payload.get("timestamp"))
    if not timestamp:
        return reject("INVALID_TIMESTAMP", f"'{payload.get('timestamp')}' is not ISO-8601")

    error_code = _text(payload, "error_code")
    masked_message, redacted = redact(message)

    return LogEvent(
        event_id=event_id_for(bucket, key, line_number),
        service=service,
        timestamp=timestamp,
        level=level,
        message=masked_message,
        fingerprint=fingerprint_for(service, error_code, masked_message),
        source_s3_uri=f"s3://{bucket}/{key}",
        line_number=line_number,
        error_code=error_code,
        endpoint=_text(payload, "endpoint"),
        ip_address=_text(payload, "ip_address"),
        request_id=_text(payload, "request_id"),
        pii_redacted=redacted,
    )


def parse_lines(lines: Iterable[str], bucket: str, key: str) -> Batch:
    """Stream a file line by line; one bad line never aborts the rest."""
    batch = Batch(source_s3_uri=f"s3://{bucket}/{key}")
    for line_number, raw in enumerate(lines, start=1):
        result = parse_line(raw, bucket, key, line_number)
        if isinstance(result, LogEvent):
            batch.events.append(result)
        else:
            batch.rejections.append(result)
    return batch
