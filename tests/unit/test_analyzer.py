"""
Unit tests for the Python Log Analyzer.
Tests parsing, schema validation, severity classification, event ID generation, and error resilience.
"""
import json
from backend.analyzer import (
    AnalysisResult,
    LogEvent,
    S3Context,
    analyze_log_line,
    generate_event_id,
    validate_iso8601_timestamp,
)


def create_test_context(line_number: int = 1) -> S3Context:
    """Helper to generate standard test S3 context."""
    return S3Context(
        bucket_name="cloudlog-test-bucket",
        object_key="2026/09/05/app-logs.jsonl",
        line_number=line_number,
    )


# ---------------------------------------------------------------------------
# 1. Valid Log Level Tests (INFO, WARNING, ERROR, CRITICAL)
# ---------------------------------------------------------------------------

def test_valid_info_log():
    """Verify parsing and classification of a valid INFO log."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:00:00.000Z",
        "service": "auth-service",
        "level": "INFO",
        "message": "User session started successfully",
    })
    ctx = create_test_context(line_number=1)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is True
    assert result.event is not None
    event = result.event
    assert event.service == "auth-service"
    assert event.level == "INFO"
    assert event.message == "User session started successfully"
    assert event.timestamp == "2026-09-05T10:00:00.000Z"
    assert event.is_incident is False
    assert event.requires_alert is False
    assert event.sort_key == f"2026-09-05T10:00:00.000Z#{event.event_id}"
    assert event.source_s3_uri == "s3://cloudlog-test-bucket/2026/09/05/app-logs.jsonl"
    assert event.line_number == 1


def test_valid_warning_log():
    """Verify parsing and classification of a valid WARNING log."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:05:00.123Z",
        "service": "payment-service",
        "level": "WARNING",
        "message": "Response time degraded (1800ms)",
    })
    ctx = create_test_context(line_number=2)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is True
    assert result.event is not None
    assert result.event.level == "WARNING"
    assert result.event.is_incident is False
    assert result.event.requires_alert is False


def test_valid_error_log():
    """Verify parsing and classification of a valid ERROR log (creates incident, no alert)."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:10:00.500Z",
        "service": "payment-service",
        "level": "ERROR",
        "message": "Payment gateway timeout after 5000ms",
        "error_code": "PGW_504",
    })
    ctx = create_test_context(line_number=3)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is True
    assert result.event is not None
    event = result.event
    assert event.level == "ERROR"
    assert event.error_code == "PGW_504"
    assert event.is_incident is True
    assert event.requires_alert is False


def test_valid_critical_log():
    """Verify parsing and classification of a valid CRITICAL log (creates incident and alert)."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:15:00.000Z",
        "service": "database-cluster",
        "level": "CRITICAL",
        "message": "Primary database node offline: connection refused",
        "error_code": "DB_CONN_REFUSED",
    })
    ctx = create_test_context(line_number=4)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is True
    assert result.event is not None
    event = result.event
    assert event.level == "CRITICAL"
    assert event.error_code == "DB_CONN_REFUSED"
    assert event.is_incident is True
    assert event.requires_alert is True


# ---------------------------------------------------------------------------
# 2. Optional Fields Extraction Tests
# ---------------------------------------------------------------------------

def test_optional_fields_present():
    """Verify extraction of error_code, endpoint, and ip_address when present."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:20:00Z",
        "service": "api-gateway",
        "level": "ERROR",
        "message": "Invalid authentication token",
        "error_code": "AUTH_TOKEN_EXPIRED",
        "endpoint": "/v1/orders",
        "ip_address": "198.51.100.24",
    })
    ctx = create_test_context(line_number=5)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is True
    assert result.event is not None
    event = result.event
    assert event.error_code == "AUTH_TOKEN_EXPIRED"
    assert event.endpoint == "/v1/orders"
    assert event.ip_address == "198.51.100.24"

    # Verify DynamoDB item dictionary contains all fields
    item = event.to_dynamodb_item()
    assert item["error_code"] == "AUTH_TOKEN_EXPIRED"
    assert item["endpoint"] == "/v1/orders"
    assert item["ip_address"] == "198.51.100.24"


def test_optional_fields_omitted():
    """Verify optional fields are None when omitted from log payload."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:25:00Z",
        "service": "user-service",
        "level": "INFO",
        "message": "Profile updated",
    })
    ctx = create_test_context(line_number=6)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is True
    assert result.event is not None
    event = result.event
    assert event.error_code is None
    assert event.endpoint is None
    assert event.ip_address is None

    # DynamoDB item should omit None keys to keep items lean
    item = event.to_dynamodb_item()
    assert "error_code" not in item
    assert "endpoint" not in item
    assert "ip_address" not in item


# ---------------------------------------------------------------------------
# 3. Validation Failure & Edge Case Tests
# ---------------------------------------------------------------------------

def test_missing_required_field():
    """Verify structured rejection when required fields are missing."""
    # Missing 'message' and 'level'
    raw = json.dumps({
        "timestamp": "2026-09-05T10:30:00Z",
        "service": "auth-service",
    })
    ctx = create_test_context(line_number=7)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "MISSING_REQUIRED_FIELDS"
    assert "level" in result.error_message
    assert "message" in result.error_message
    assert result.line_number == 7


def test_invalid_json():
    """Verify structured rejection when a line contains malformed JSON."""
    raw = '{"timestamp": "2026-09-05T10:00:00Z", "service": "auth-service", unclosed_json'
    ctx = create_test_context(line_number=8)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "INVALID_JSON"
    assert result.line_number == 8


def test_invalid_json_non_dict():
    """Verify rejection when JSON is a primitive or array rather than an object."""
    raw = '["item1", "item2"]'
    ctx = create_test_context(line_number=9)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "INVALID_JSON_OBJECT"


def test_empty_line():
    """Verify rejection of empty or whitespace-only lines."""
    ctx = create_test_context(line_number=10)
    result = analyze_log_line("   \n", ctx)

    assert result.is_valid is False
    assert result.error_type == "EMPTY_LINE"


def test_invalid_log_level():
    """Verify rejection of unsupported log severity levels."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:00:00Z",
        "service": "auth-service",
        "level": "FATAL",  # Not in allowed MVP levels
        "message": "Fatal system condition",
    })
    ctx = create_test_context(line_number=11)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "INVALID_LOG_LEVEL"
    assert "FATAL" in result.error_message


def test_invalid_timestamp():
    """Verify rejection of invalid timestamp formats."""
    raw = json.dumps({
        "timestamp": "yesterday at 5pm",
        "service": "auth-service",
        "level": "INFO",
        "message": "User logged in",
    })
    ctx = create_test_context(line_number=12)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "INVALID_TIMESTAMP"


def test_empty_service_name():
    """Verify rejection when service name is empty or whitespace."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:00:00Z",
        "service": "   ",
        "level": "INFO",
        "message": "User logged in",
    })
    ctx = create_test_context(line_number=13)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "EMPTY_SERVICE"


def test_empty_message():
    """Verify rejection when message is empty or whitespace."""
    raw = json.dumps({
        "timestamp": "2026-09-05T10:00:00Z",
        "service": "auth-service",
        "level": "INFO",
        "message": "",
    })
    ctx = create_test_context(line_number=14)
    result = analyze_log_line(raw, ctx)

    assert result.is_valid is False
    assert result.error_type == "EMPTY_MESSAGE"


# ---------------------------------------------------------------------------
# 4. Deterministic Event ID & Idempotency Tests
# ---------------------------------------------------------------------------

def test_deterministic_event_id():
    """Verify identical S3 bucket, key, and line number generate the exact same event_id."""
    id1 = generate_event_id("my-bucket", "2026/09/05/logs.jsonl", 42)
    id2 = generate_event_id("my-bucket", "2026/09/05/logs.jsonl", 42)
    id3 = generate_event_id("my-bucket", "2026/09/05/logs.jsonl", 43)

    assert id1.startswith("evt_")
    assert len(id1) == 20  # "evt_" (4 chars) + 16 hex chars
    assert id1 == id2  # Idempotent match
    assert id1 != id3  # Different line number produces different ID


def test_timestamp_validator_helper():
    """Direct tests for the ISO 8601 validation helper."""
    assert validate_iso8601_timestamp("2026-09-05T14:30:00.123Z") is True
    assert validate_iso8601_timestamp("2026-09-05T14:30:00+00:00") is True
    assert validate_iso8601_timestamp("2026-09-05T14:30:00") is True
    assert validate_iso8601_timestamp("2026-09-05") is True
    assert validate_iso8601_timestamp("invalid-date") is False
    assert validate_iso8601_timestamp(123456789) is False
    assert validate_iso8601_timestamp(None) is False
