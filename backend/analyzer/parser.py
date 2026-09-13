"""
Pure Python Log Analyzer & Parser.
Extracts, validates, classifies, and enriches JSONL log events without external cloud SDKs.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional, Set

from backend.analyzer.models import AnalysisResult, LogEvent, S3Context
from backend.common.config import (
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    VALID_SEVERITIES,
)

REQUIRED_FIELDS: Set[str] = {"timestamp", "service", "level", "message"}


def generate_event_id(bucket_name: str, object_key: str, line_number: int) -> str:
    """
    Generate a deterministic 16-hex character event ID based on S3 location metadata.
    Format: evt_ + SHA256(bucket:key:line_number)[:16]
    Provides idempotent re-processing for AWS Lambda retries.
    """
    raw_identifier = f"{bucket_name}:{object_key}:{line_number}"
    sha256_hash = hashlib.sha256(raw_identifier.encode("utf-8")).hexdigest()
    return f"evt_{sha256_hash[:16]}"


def validate_iso8601_timestamp(ts_value: Any) -> bool:
    """Validate that a timestamp value is a valid ISO 8601 string."""
    if not isinstance(ts_value, str) or not ts_value.strip():
        return False
    try:
        # Normalize trailing 'Z' to UTC '+00:00' for Python fromisoformat parser
        normalized = ts_value.strip().replace("Z", "+00:00")
        datetime.fromisoformat(normalized)
        return True
    except (ValueError, TypeError):
        return False


def _clean_optional_string(raw_dict: dict, field_name: str) -> Optional[str]:
    """Helper to extract non-empty optional string fields."""
    val = raw_dict.get(field_name)
    if val is None:
        return None
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def analyze_log_line(raw_line: str, context: S3Context) -> AnalysisResult:
    """
    Parse, validate, classify, and enrich a single raw JSONL line.

    Args:
        raw_line: Raw text line containing a single JSON log record.
        context: S3 origin metadata (bucket_name, object_key, line_number).

    Returns:
        AnalysisResult containing either a validated LogEvent or structured error details.
    """
    source_uri = context.source_s3_uri
    line_num = context.line_number

    # 1. Check for empty or whitespace-only lines
    if not isinstance(raw_line, str) or not raw_line.strip():
        return AnalysisResult(
            is_valid=False,
            error_type="EMPTY_LINE",
            error_message="Log line is empty or contains only whitespace",
            line_number=line_num,
            source_s3_uri=source_uri,
        )

    # 2. Parse JSON syntax
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        return AnalysisResult(
            is_valid=False,
            error_type="INVALID_JSON",
            error_message=f"JSON decoding error: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            line_number=line_num,
            source_s3_uri=source_uri,
        )

    if not isinstance(payload, dict):
        return AnalysisResult(
            is_valid=False,
            error_type="INVALID_JSON_OBJECT",
            error_message="Log line must be a JSON object (key-value dictionary)",
            line_number=line_num,
            source_s3_uri=source_uri,
        )

    # 3. Check for required fields
    missing_fields = sorted(list(REQUIRED_FIELDS - payload.keys()))
    if missing_fields:
        return AnalysisResult(
            is_valid=False,
            error_type="MISSING_REQUIRED_FIELDS",
            error_message=f"Missing required field(s): {', '.join(missing_fields)}",
            line_number=line_num,
            source_s3_uri=source_uri,
        )

    # 4. Validate service name
    service = payload.get("service")
    if not isinstance(service, str) or not service.strip():
        return AnalysisResult(
            is_valid=False,
            error_type="EMPTY_SERVICE",
            error_message="Field 'service' must be a non-empty string",
            line_number=line_num,
            source_s3_uri=source_uri,
        )
    service = service.strip()

    # 5. Validate log message
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return AnalysisResult(
            is_valid=False,
            error_type="EMPTY_MESSAGE",
            error_message="Field 'message' must be a non-empty string",
            line_number=line_num,
            source_s3_uri=source_uri,
        )
    message = message.strip()

    # 6. Validate log level
    raw_level = payload.get("level")
    if not isinstance(raw_level, str) or raw_level.strip().upper() not in VALID_SEVERITIES:
        allowed = ", ".join(sorted(list(VALID_SEVERITIES)))
        return AnalysisResult(
            is_valid=False,
            error_type="INVALID_LOG_LEVEL",
            error_message=f"Invalid log level '{raw_level}'. Allowed levels: {allowed}",
            line_number=line_num,
            source_s3_uri=source_uri,
        )
    level = raw_level.strip().upper()

    # 7. Validate timestamp format
    raw_timestamp = payload.get("timestamp")
    if not validate_iso8601_timestamp(raw_timestamp):
        return AnalysisResult(
            is_valid=False,
            error_type="INVALID_TIMESTAMP",
            error_message=f"Invalid ISO 8601 timestamp format: '{raw_timestamp}'",
            line_number=line_num,
            source_s3_uri=source_uri,
        )
    timestamp = str(raw_timestamp).strip()

    # 8. Extract optional contextual fields
    error_code = _clean_optional_string(payload, "error_code")
    endpoint = _clean_optional_string(payload, "endpoint")
    ip_address = _clean_optional_string(payload, "ip_address")

    # 9. Generate deterministic event_id and DynamoDB sort key
    event_id = generate_event_id(context.bucket_name, context.object_key, line_num)
    sort_key = f"{timestamp}#{event_id}"

    # 10. Operational classification
    is_incident = level in {SEVERITY_ERROR, SEVERITY_CRITICAL}
    requires_alert = level == SEVERITY_CRITICAL

    processed_at = datetime.now(timezone.utc).isoformat()

    event = LogEvent(
        event_id=event_id,
        service=service,
        timestamp=timestamp,
        sort_key=sort_key,
        level=level,
        message=message,
        source_s3_uri=source_uri,
        line_number=line_num,
        processed_at=processed_at,
        is_incident=is_incident,
        requires_alert=requires_alert,
        error_code=error_code,
        endpoint=endpoint,
        ip_address=ip_address,
    )

    return AnalysisResult(
        is_valid=True,
        event=event,
        line_number=line_num,
        source_s3_uri=source_uri,
    )
