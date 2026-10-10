from unittest.mock import MagicMock

import pytest

from backend.handlers.processor import Processor
from backend.storage.events import EventsStore
from backend.storage.incidents import IncidentsStore
from backend.storage.runs import RunsStore
from tests.conftest import jsonl, log


@pytest.fixture
def processor(aws):
    return Processor(s3=aws.s3)


def upload(aws, key, body, **meta):
    aws.s3.put_object(Bucket=aws.names["bucket"], Key=key, Body=body.encode(), Metadata=meta)


def s3_event(aws, key):
    return {"Records": [{"s3": {"bucket": {"name": aws.names["bucket"]}, "object": {"key": key}}}]}


def test_full_pipeline_stores_detects_alerts_and_records_the_run(aws, processor):
    upload(aws, "raw-logs/simulations/x/db.jsonl", jsonl(
        log(),
        log(level="ERROR", message="Query timed out after 5000ms", error_code="DB_TIMEOUT"),
        log(level="CRITICAL", service="db", message="Primary down", error_code="DB_DOWN"),
        "not json",
    ), scenario="db-outage", **{"triggered-by": "ana@x"})

    result = processor.handle(s3_event(aws, "raw-logs/simulations/x/db.jsonl"))
    [run] = result["runs"]

    assert (run["status"], run["stored"], run["rejected"], run["total_lines"]) == ("SUCCESS", 3, 1, 4)
    assert run["trigger"] == "simulator" and run["scenario"] == "db-outage" and run["triggered_by"] == "ana@x"
    assert {d["rule_id"] for d in run["detections"]} == {"error-log", "critical-log"}
    assert len(run["alerts"]) == 1 and run["alerts"][0]["subject"].startswith("[CloudLog CRITICAL] db")
    assert set(run["stages"]) == {"s3_read_ms", "parse_ms", "store_ms", "detect_ms", "alert_ms"}

    assert len(EventsStore().recent(limit=10)) == 3
    assert {i["severity"] for i in IncidentsStore().list()} == {"ERROR", "CRITICAL"}
    assert RunsStore().recent()[0]["run_id"] == run["run_id"]

    [message] = aws.inbox()
    assert "Primary down" in message["Message"]
    assert message["MessageAttributes"]["severity"]["Value"] == "CRITICAL"


def test_lambda_retry_of_the_same_file_does_not_double_count(aws, processor):
    upload(aws, "raw-logs/a.jsonl", jsonl(*[log(level="ERROR", message="boom", error_code="E")] * 2))
    processor.handle(s3_event(aws, "raw-logs/a.jsonl"))
    processor.handle(s3_event(aws, "raw-logs/a.jsonl"))
    [incident] = IncidentsStore().list()
    assert incident["occurrences"] == 2
    assert len(EventsStore().recent(limit=10)) == 2  # same event IDs -> overwritten, not duplicated


def test_url_encoded_keys_are_decoded(aws, processor):
    upload(aws, "raw-logs/my file.jsonl", jsonl(log()))
    result = processor.handle(s3_event(aws, "raw-logs/my+file.jsonl"))
    assert result["runs"][0]["stored"] == 1


def test_non_jsonl_objects_and_malformed_records_are_ignored(aws, processor):
    upload(aws, "raw-logs/readme.txt", "hello")
    event = s3_event(aws, "raw-logs/readme.txt")
    event["Records"].append({"s3": {}})
    assert processor.handle(event)["processed_files"] == 0


def test_failures_are_recorded_and_re_raised_for_lambda_retry(aws):
    broken = MagicMock()
    broken.save.side_effect = RuntimeError("DynamoDB throttled")
    processor = Processor(s3=aws.s3, events=broken)
    upload(aws, "raw-logs/a.jsonl", jsonl(log()))
    with pytest.raises(RuntimeError):
        processor.handle(s3_event(aws, "raw-logs/a.jsonl"))
    [run] = RunsStore().recent()
    assert run["status"] == "FAILED" and "throttled" in run["error"]


def test_alerting_is_skipped_without_a_topic(aws, monkeypatch):
    monkeypatch.setenv("SNS_ALERT_TOPIC_ARN", "")
    processor = Processor(s3=aws.s3)
    upload(aws, "raw-logs/a.jsonl", jsonl(log(level="CRITICAL", message="down")))
    run = processor.handle(s3_event(aws, "raw-logs/a.jsonl"))["runs"][0]
    assert run["alerts"] == [] and run["detections"][0]["severity"] == "CRITICAL"


def test_stored_events_mask_ip_addresses(aws, processor):
    upload(aws, "raw-logs/a.jsonl", jsonl(log(ip_address="198.51.100.7")))
    processor.handle(s3_event(aws, "raw-logs/a.jsonl"))
    assert EventsStore().recent()[0]["ip_address"] == "198.51.100.x"


def test_repeated_attacks_from_one_ip_join_the_same_security_incident(aws, processor):
    from backend.simulator.scenarios import render
    for key in ("raw-logs/attack-1.jsonl", "raw-logs/attack-2.jsonl"):
        upload(aws, key, "\n".join(render("brute-force")) + "\n")
        processor.handle(s3_event(aws, key))
    [incident] = IncidentsStore().list()
    assert (incident["category"], incident["occurrences"], incident["source_ip"]) == ("Security", 14, "203.0.113.42")
    assert incident["title"] == "Possible brute-force login attack from 203.0.113.42"
    assert len(aws.inbox()) == 1  # alerted when opened, not again for the repeat
