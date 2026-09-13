"""
Unit tests for the Log Ingestion Reader.
Tests streaming JSONL files line-by-line, fault isolation, line numbering, and empty files.
"""
import io
import json
from pathlib import Path

from backend.ingestion import IngestionBatchResult, ingest_jsonl_file, ingest_jsonl_stream


def test_ingest_multiple_valid_lines(tmp_path: Path):
    """Verify ingestion of a JSONL file with multiple valid log records."""
    log_records = [
        {
            "timestamp": "2026-09-05T10:00:00.000Z",
            "service": "auth-service",
            "level": "INFO",
            "message": "User authenticated",
        },
        {
            "timestamp": "2026-09-05T10:00:01.000Z",
            "service": "payment-service",
            "level": "WARNING",
            "message": "Gateway high latency",
        },
        {
            "timestamp": "2026-09-05T10:00:02.000Z",
            "service": "order-service",
            "level": "ERROR",
            "message": "Order creation failed",
            "error_code": "ORDER_ERR_500",
        },
    ]

    test_file = tmp_path / "valid_logs.jsonl"
    with open(test_file, "w", encoding="utf-8") as f:
        for record in log_records:
            f.write(json.dumps(record) + "\n")

    batch: IngestionBatchResult = ingest_jsonl_file(
        file_path=test_file,
        bucket_name="my-logs-bucket",
        object_key="2026/09/05/valid_logs.jsonl",
    )

    assert batch.source_s3_uri == "s3://my-logs-bucket/2026/09/05/valid_logs.jsonl"
    assert batch.total_lines == 3
    assert batch.valid_count == 3
    assert batch.invalid_count == 0

    # Verify line numbers are correctly 1-indexed
    assert [event.line_number for event in batch.valid_events] == [1, 2, 3]

    # Verify services and levels
    assert batch.valid_events[0].service == "auth-service"
    assert batch.valid_events[0].level == "INFO"
    assert batch.valid_events[1].service == "payment-service"
    assert batch.valid_events[1].level == "WARNING"
    assert batch.valid_events[2].service == "order-service"
    assert batch.valid_events[2].level == "ERROR"
    assert batch.valid_events[2].error_code == "ORDER_ERR_500"


def test_ingest_mixture_valid_and_invalid_lines(tmp_path: Path):
    """Verify ingestion handles a mixture of valid and malformed lines."""
    lines = [
        json.dumps({
            "timestamp": "2026-09-05T10:00:00Z",
            "service": "auth-service",
            "level": "INFO",
            "message": "Valid line 1",
        }),
        '{"timestamp": "2026-09-05T10:00:01Z", malformed_json',  # Line 2: Bad JSON syntax
        json.dumps({
            "timestamp": "2026-09-05T10:00:02Z",
            "service": "order-service",
            "level": "WARNING",
            "message": "Valid line 3",
        }),
        json.dumps({
            "timestamp": "2026-09-05T10:00:03Z",
            "service": "payment-service",
            # Line 4: Missing required 'level' and 'message'
        }),
        json.dumps({
            "timestamp": "2026-09-05T10:00:04Z",
            "service": "order-service",
            "level": "CRITICAL",
            "message": "Valid line 5",
        }),
    ]

    test_file = tmp_path / "mixed_logs.jsonl"
    test_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    batch = ingest_jsonl_file(
        file_path=test_file,
        bucket_name="my-logs-bucket",
        object_key="2026/09/05/mixed_logs.jsonl",
    )

    assert batch.total_lines == 5
    assert batch.valid_count == 3
    assert batch.invalid_count == 2

    # Verify line numbers of valid records
    assert [e.line_number for e in batch.valid_events] == [1, 3, 5]

    # Verify line numbers and classifications of rejected records
    assert batch.invalid_records[0].line_number == 2
    assert batch.invalid_records[0].error_type == "INVALID_JSON"

    assert batch.invalid_records[1].line_number == 4
    assert batch.invalid_records[1].error_type == "MISSING_REQUIRED_FIELDS"


def test_processing_continues_after_invalid_line():
    """Verify that a malformed line does not abort remaining valid records."""
    raw_stream = io.StringIO(
        '{"timestamp": "2026-09-05T10:00:00Z", "service": "s1", "level": "INFO", "message": "First"}\n'
        'CORRUPTED_LINE_THAT_IS_NOT_JSON\n'
        '{"timestamp": "2026-09-05T10:00:02Z", "service": "s2", "level": "ERROR", "message": "Third"}\n'
    )

    batch = ingest_jsonl_stream(
        stream=raw_stream,
        bucket_name="test-bucket",
        object_key="stream.jsonl",
    )

    assert batch.total_lines == 3
    assert batch.valid_count == 2
    assert batch.invalid_count == 1

    # First and third records must succeed
    assert batch.valid_events[0].message == "First"
    assert batch.valid_events[0].line_number == 1
    assert batch.valid_events[1].message == "Third"
    assert batch.valid_events[1].line_number == 3

    # Second record was flagged as invalid
    assert batch.invalid_records[0].line_number == 2
    assert batch.invalid_records[0].error_type == "INVALID_JSON"


def test_correct_line_numbers_and_s3_context():
    """Verify S3Context metadata is accurately constructed for each line."""
    raw_stream = io.StringIO(
        '{"timestamp": "2026-09-05T12:00:00Z", "service": "api", "level": "INFO", "message": "msg 1"}\n'
        '{"timestamp": "2026-09-05T12:00:01Z", "service": "api", "level": "INFO", "message": "msg 2"}\n'
    )

    batch = ingest_jsonl_stream(
        stream=raw_stream,
        bucket_name="audit-bucket",
        object_key="nested/dir/logs.jsonl",
    )

    assert batch.total_lines == 2
    event1 = batch.valid_events[0]
    event2 = batch.valid_events[1]

    assert event1.line_number == 1
    assert event1.source_s3_uri == "s3://audit-bucket/nested/dir/logs.jsonl"

    assert event2.line_number == 2
    assert event2.source_s3_uri == "s3://audit-bucket/nested/dir/logs.jsonl"

    # Deterministic event_id values must differ because line numbers differ
    assert event1.event_id != event2.event_id


def test_empty_file(tmp_path: Path):
    """Verify that an empty JSONL file produces zero events without error."""
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("", encoding="utf-8")

    batch = ingest_jsonl_file(
        file_path=empty_file,
        bucket_name="test-bucket",
        object_key="empty.jsonl",
    )

    assert batch.total_lines == 0
    assert batch.valid_count == 0
    assert batch.invalid_count == 0
    assert len(batch.valid_events) == 0
    assert len(batch.invalid_records) == 0
