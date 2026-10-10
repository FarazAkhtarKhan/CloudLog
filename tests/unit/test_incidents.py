import pytest

from backend.analyzer.detector import Detection
from backend.config import ESCALATION_THRESHOLD
from backend.storage.incidents import IncidentsStore, InvalidTransition


def detection(count=1, severity="ERROR", fingerprint="fp1", **kw):
    fields = dict(fingerprint=fingerprint, rule_id="error-log", severity=severity, category="Failure",
                  service="payments", title="Timeout", error_code="PGW_TIMEOUT",
                  first_seen="2026-10-10T10:00:00.000Z", last_seen="2026-10-10T10:00:05.000Z", count=count)
    fields.update(kw)
    return Detection(**fields)


@pytest.fixture
def store(aws):
    return IncidentsStore(dynamodb=aws.dynamodb)


def test_first_detection_opens_an_incident(store):
    result = store.apply(detection(count=2), "s3://b/1.jsonl")
    assert result.outcome == "opened" and result.alert is False
    item = store.get("inc_fp1")
    assert (item["status"], item["occurrences"], item["severity"]) == ("OPEN", 2, "ERROR")
    assert item["timeline"][0]["type"] == "opened"


def test_repeats_from_other_files_increment_the_same_incident(store):
    store.apply(detection(count=2), "s3://b/1.jsonl")
    result = store.apply(detection(count=1, last_seen="2026-10-10T11:00:00.000Z"), "s3://b/2.jsonl")
    assert result.outcome == "updated"
    item = store.get("inc_fp1")
    assert item["occurrences"] == 3
    assert item["last_seen"] == "2026-10-10T11:00:00.000Z"
    assert item["source_files"] == {"s3://b/1.jsonl", "s3://b/2.jsonl"}


def test_reprocessing_the_same_file_is_idempotent(store):
    store.apply(detection(count=2), "s3://b/1.jsonl")
    result = store.apply(detection(count=2), "s3://b/1.jsonl")
    assert result.outcome == "duplicate" and result.alert is False
    assert store.get("inc_fp1")["occurrences"] == 2


def test_error_escalates_to_critical_at_the_threshold(store):
    store.apply(detection(count=ESCALATION_THRESHOLD - 1), "s3://b/1.jsonl")
    result = store.apply(detection(count=1), "s3://b/2.jsonl")
    assert result.escalated and result.alert
    item = store.get("inc_fp1")
    assert item["severity"] == "CRITICAL" and item["escalated"] is True
    # already critical: further repeats do not alert again
    assert store.apply(detection(count=1), "s3://b/3.jsonl").alert is False


def test_a_critical_line_escalates_an_existing_error(store):
    store.apply(detection(), "s3://b/1.jsonl")
    assert store.apply(detection(severity="CRITICAL"), "s3://b/2.jsonl").escalated


def test_large_first_batch_opens_already_escalated(store):
    result = store.apply(detection(count=ESCALATION_THRESHOLD), "s3://b/1.jsonl")
    assert result.incident["severity"] == "CRITICAL" and result.alert


def test_new_critical_incident_requests_an_alert(store):
    assert store.apply(detection(severity="CRITICAL"), "s3://b/1.jsonl").alert


def test_lifecycle_open_acknowledge_resolve(store):
    store.apply(detection(), "s3://b/1.jsonl")
    acked = store.acknowledge("inc_fp1", by="ana@x", note="on it")
    assert acked["status"] == "ACKNOWLEDGED" and acked["acknowledged_by"] == "ana@x"
    resolved = store.resolve("inc_fp1", by="ana@x")
    assert resolved["status"] == "RESOLVED" and resolved["resolved_at"]
    assert [t["type"] for t in resolved["timeline"]] == ["opened", "acknowledged", "resolved"]
    assert "on it" in resolved["timeline"][1]["detail"]


def test_invalid_transitions_and_missing_incidents(store):
    store.apply(detection(), "s3://b/1.jsonl")
    store.resolve("inc_fp1", by="a")
    with pytest.raises(InvalidTransition):
        store.acknowledge("inc_fp1", by="a")
    with pytest.raises(InvalidTransition):
        store.resolve("inc_fp1", by="a")
    assert store.resolve("inc_missing", by="a") is None


def test_resolved_incident_reopens_on_regression(store):
    store.apply(detection(), "s3://b/1.jsonl")
    store.resolve("inc_fp1", by="a")
    result = store.apply(detection(), "s3://b/2.jsonl")
    assert result.outcome == "reopened"
    item = store.get("inc_fp1")
    assert (item["status"], item["reopen_count"], item["occurrences"]) == ("OPEN", 1, 1)
    assert [t["type"] for t in item["timeline"]][-2:] == ["reopened", "opened"]


def test_list_filters_by_status_newest_first(store):
    store.apply(detection(fingerprint="a"), "s3://b/1.jsonl")
    store.apply(detection(fingerprint="b"), "s3://b/1.jsonl")
    store.resolve("inc_a", by="x")
    assert [i["incident_id"] for i in store.list(status="OPEN")] == ["inc_b"]
    assert [i["incident_id"] for i in store.list()] == ["inc_a", "inc_b"]


def test_record_alert_adds_to_timeline(store):
    store.apply(detection(severity="CRITICAL"), "s3://b/1.jsonl")
    store.record_alert("inc_fp1", "msg-123")
    item = store.get("inc_fp1")
    assert item["alerts_sent"] == 1 and "msg-123" in item["timeline"][-1]["detail"]
