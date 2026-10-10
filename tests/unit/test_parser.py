import json

import pytest

from backend.analyzer.models import LogEvent, Rejection
from backend.analyzer.parser import (
    event_id_for,
    fingerprint_for,
    message_shape,
    normalise_timestamp,
    parse_line,
    parse_lines,
)
from backend.analyzer.privacy import mask_ip, redact
from tests.conftest import log


def parse(payload, line=1):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return parse_line(raw, "bucket", "logs/a.jsonl", line)


def test_valid_line_is_normalised():
    event = parse(log(level=" error ", service=" payments ", ts="2026-10-10T15:30:00+05:30",
                      error_code="PGW_TIMEOUT", ip_address="10.1.2.3"))
    assert isinstance(event, LogEvent)
    assert event.level == "ERROR"
    assert event.service == "payments"
    assert event.timestamp == "2026-10-10T10:00:00.000Z"  # converted to UTC
    assert event.sort_key == f"2026-10-10T10:00:00.000Z#{event.event_id}"
    assert event.feed_day == "2026-10-10"
    assert event.source_s3_uri == "s3://bucket/logs/a.jsonl"


@pytest.mark.parametrize("raw, reason", [
    ("", "EMPTY_LINE"),
    ("{not json", "INVALID_JSON"),
    ("[1, 2]", "INVALID_JSON"),
    (json.dumps({"service": "a", "level": "INFO"}), "MISSING_FIELDS"),
    (json.dumps(log(service="  ")), "MISSING_FIELDS"),
    (json.dumps(log(level="FATAL")), "INVALID_LEVEL"),
    (json.dumps(log(ts="yesterday")), "INVALID_TIMESTAMP"),
])
def test_invalid_lines_are_rejected_with_a_reason(raw, reason):
    result = parse(raw)
    assert isinstance(result, Rejection)
    assert result.reason == reason
    assert result.line_number == 1


def test_one_bad_line_does_not_stop_the_file():
    batch = parse_lines([json.dumps(log()), "oops", json.dumps(log(level="ERROR"))], "b", "k.jsonl")
    assert batch.total_lines == 3
    assert [e.line_number for e in batch.events] == [1, 3]
    assert batch.rejections[0].line_number == 2


def test_event_ids_are_deterministic_for_retries():
    assert event_id_for("b", "k", 4) == event_id_for("b", "k", 4)
    assert event_id_for("b", "k", 4) != event_id_for("b", "k", 5)
    assert parse(log(), 7).event_id == parse(log(), 7).event_id


def test_fingerprint_ignores_volatile_numbers():
    a = parse(log(level="ERROR", message="Timeout after 5012ms on 10.0.0.4"))
    b = parse(log(level="ERROR", message="Timeout after 5390ms on 10.0.0.9"))
    c = parse(log(level="ERROR", message="Disk full"))
    assert a.fingerprint == b.fingerprint != c.fingerprint
    assert message_shape("Timeout after 5012ms") == "timeout after #ms"


def test_fingerprint_prefers_error_code_and_includes_service():
    assert fingerprint_for("svc", "E1", "one") == fingerprint_for("svc", "e1", "two")
    assert fingerprint_for("svc", "E1", "x") != fingerprint_for("other", "E1", "x")


def test_pii_in_messages_is_masked():
    event = parse(log(message="Charge failed for jane.doe@mail.com card 4111 1111 1111 1234 from 192.168.4.20"))
    assert event.message == "Charge failed for j***@mail.com card ****-****-****-1234 from 192.168.4.x"
    assert event.pii_redacted is True
    assert parse(log(message="nothing personal")).pii_redacted is False


def test_redaction_helpers():
    assert redact("no pii") == ("no pii", False)
    assert mask_ip("203.0.113.42") == "203.0.113.x"


def test_naive_timestamps_are_treated_as_utc():
    assert normalise_timestamp("2026-01-02T03:04:05") == "2026-01-02T03:04:05.000Z"
    assert normalise_timestamp(12345) is None
