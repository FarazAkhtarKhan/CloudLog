"""
Unit tests for the CloudLog Incidents layer using Moto.
Tests incident generation from LogEvents, deterministic IDs, idempotency,
DynamoDB persistence, GSI queries, and lifecycle resolution.
"""
import boto3
import pytest
from moto import mock_aws

from backend.analyzer.models import LogEvent
from backend.incidents import (
    INCIDENT_INDEX_NAME,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Incident,
    IncidentsRepository,
    create_incident_from_event,
    generate_incident_id,
)

TEST_INCIDENTS_TABLE = "cloudlog_incidents_test"
TEST_REGION = "us-east-1"


@pytest.fixture
def mock_incidents_table():
    """Sets up an in-memory mock DynamoDB table with the GSI for incidents."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = dynamodb.create_table(
            TableName=TEST_INCIDENTS_TABLE,
            KeySchema=[
                {"AttributeName": "incident_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "incident_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": INCIDENT_INDEX_NAME,
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield dynamodb


def make_test_event(
    level: str,
    event_id: str = "evt_8f14c2b9a70e31d4",
    service: str = "order-service",
    message: str = "Test message",
    error_code: str = None,
) -> LogEvent:
    """Helper to construct a LogEvent with specified level and event_id."""
    return LogEvent(
        event_id=event_id,
        service=service,
        timestamp="2026-09-05T14:30:00.000Z",
        sort_key=f"2026-09-05T14:30:00.000Z#{event_id}",
        level=level,
        message=message,
        source_s3_uri="s3://test-bucket/app.jsonl",
        line_number=10,
        processed_at="2026-09-05T14:30:01.000Z",
        is_incident=(level in {"ERROR", "CRITICAL"}),
        requires_alert=(level == "CRITICAL"),
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# Generator Logic Tests (Pure Python)
# ---------------------------------------------------------------------------

def test_error_event_creates_incident():
    """Verify that an ERROR LogEvent produces an Incident with status OPEN."""
    event = make_test_event(
        level="ERROR",
        event_id="evt_8f14c2b9a70e31d4",
        service="payment-service",
        message="Payment timeout",
        error_code="PGW_504",
    )
    incident = create_incident_from_event(event)

    assert incident is not None
    assert incident.incident_id == "inc_8f14c2b9a70e31d4"
    assert incident.service == "payment-service"
    assert incident.severity == "ERROR"
    assert incident.status == STATUS_OPEN
    assert incident.message == "Payment timeout"
    assert incident.error_code == "PGW_504"
    assert incident.source_event_id == "evt_8f14c2b9a70e31d4"
    assert incident.source_s3_uri == "s3://test-bucket/app.jsonl"
    assert incident.resolved_at is None


def test_critical_event_creates_incident():
    """Verify that a CRITICAL LogEvent produces an Incident with status OPEN."""
    event = make_test_event(
        level="CRITICAL",
        event_id="evt_c49a10ef582103ba",
        service="db-service",
        message="Primary DB offline",
        error_code="DB_OFFLINE",
    )
    incident = create_incident_from_event(event)

    assert incident is not None
    assert incident.incident_id == "inc_c49a10ef582103ba"
    assert incident.severity == "CRITICAL"
    assert incident.status == STATUS_OPEN


def test_info_and_warning_do_not_create_incidents():
    """Verify that INFO and WARNING events return None (no incident created)."""
    info_event = make_test_event(level="INFO", event_id="evt_info_1")
    warn_event = make_test_event(level="WARNING", event_id="evt_warn_1")

    assert create_incident_from_event(info_event) is None
    assert create_incident_from_event(warn_event) is None


def test_deterministic_incident_id_generation():
    """Verify consistent formula 'inc_' + hex part of event_id."""
    assert generate_incident_id("evt_1234567890abcdef") == "inc_1234567890abcdef"
    assert generate_incident_id("evt_test") == "inc_test"


# ---------------------------------------------------------------------------
# Repository Persistence & GSI Query Tests (Moto)
# ---------------------------------------------------------------------------

def test_save_and_retrieve_incident(mock_incidents_table):
    """Verify saving an incident and retrieving it by primary key."""
    repo = IncidentsRepository(
        table_name=TEST_INCIDENTS_TABLE,
        dynamodb_resource=mock_incidents_table,
    )

    event = make_test_event(level="ERROR", event_id="evt_abc1234567890def")
    incident = create_incident_from_event(event, created_at="2026-09-05T15:00:00Z")

    repo.save_incident(incident)

    fetched = repo.get_incident("inc_abc1234567890def")
    assert fetched is not None
    assert fetched.incident_id == "inc_abc1234567890def"
    assert fetched.service == "order-service"
    assert fetched.status == STATUS_OPEN
    assert fetched.severity == "ERROR"
    assert fetched.created_at == "2026-09-05T15:00:00Z"
    assert fetched.resolved_at is None


def test_duplicate_processing_idempotency(mock_incidents_table):
    """Verify saving the same incident twice overwrites in place without duplicate records."""
    repo = IncidentsRepository(
        table_name=TEST_INCIDENTS_TABLE,
        dynamodb_resource=mock_incidents_table,
    )

    event = make_test_event(level="ERROR", event_id="evt_duplicate_test")
    incident_first = create_incident_from_event(event, created_at="2026-09-05T15:00:00Z")
    incident_retry = create_incident_from_event(event, created_at="2026-09-05T15:00:00Z")

    repo.save_incident(incident_first)
    repo.save_incident(incident_retry)

    open_incidents = repo.get_open_incidents()
    # Total count in the table must still be 1
    assert len(open_incidents) == 1
    assert open_incidents[0].incident_id == "inc_duplicate_test"


def test_get_open_incidents_via_gsi(mock_incidents_table):
    """Verify querying open incidents via the GSI returns only OPEN incidents in chronological order."""
    repo = IncidentsRepository(
        table_name=TEST_INCIDENTS_TABLE,
        dynamodb_resource=mock_incidents_table,
    )

    inc1 = Incident(
        incident_id="inc_001",
        service="service-1",
        severity="ERROR",
        status=STATUS_OPEN,
        message="Error 1",
        source_event_id="evt_001",
        source_s3_uri="s3://b/k",
        created_at="2026-09-05T10:00:00Z",
    )
    inc2 = Incident(
        incident_id="inc_002",
        service="service-2",
        severity="CRITICAL",
        status=STATUS_OPEN,
        message="Error 2",
        source_event_id="evt_002",
        source_s3_uri="s3://b/k",
        created_at="2026-09-05T10:05:00Z",
    )
    inc3_resolved = Incident(
        incident_id="inc_003",
        service="service-3",
        severity="ERROR",
        status=STATUS_RESOLVED,
        message="Error 3 (already resolved)",
        source_event_id="evt_003",
        source_s3_uri="s3://b/k",
        created_at="2026-09-05T09:00:00Z",
        resolved_at="2026-09-05T09:30:00Z",
    )

    repo.save_incident(inc1)
    repo.save_incident(inc2)
    repo.save_incident(inc3_resolved)

    # Query OPEN incidents descending (newest first, scan_forward=False)
    open_list = repo.get_open_incidents(scan_forward=False)
    assert len(open_list) == 2
    assert open_list[0].incident_id == "inc_002"  # 10:05 is newer
    assert open_list[1].incident_id == "inc_001"  # 10:00 is older

    # Query OPEN incidents ascending (chronological, scan_forward=True)
    open_asc = repo.get_open_incidents(scan_forward=True)
    assert len(open_asc) == 2
    assert open_asc[0].incident_id == "inc_001"
    assert open_asc[1].incident_id == "inc_002"


def test_resolve_incident_lifecycle(mock_incidents_table):
    """Verify transitioning an incident from OPEN to RESOLVED sets status and resolved_at."""
    repo = IncidentsRepository(
        table_name=TEST_INCIDENTS_TABLE,
        dynamodb_resource=mock_incidents_table,
    )

    inc = Incident(
        incident_id="inc_lifecycle_test",
        service="payment-service",
        severity="ERROR",
        status=STATUS_OPEN,
        message="Gateway 504",
        source_event_id="evt_lifecycle_test",
        source_s3_uri="s3://b/k",
        created_at="2026-09-05T16:00:00Z",
    )
    repo.save_incident(inc)

    # Resolve incident
    resolved = repo.resolve_incident(
        incident_id="inc_lifecycle_test",
        resolved_at="2026-09-05T16:45:00Z",
    )

    assert resolved is not None
    assert resolved.incident_id == "inc_lifecycle_test"
    assert resolved.status == STATUS_RESOLVED
    assert resolved.resolved_at == "2026-09-05T16:45:00Z"

    # Verify GSI query no longer returns this incident as OPEN
    open_list = repo.get_open_incidents()
    assert len(open_list) == 0

    # Direct GetItem shows status is RESOLVED
    fetched = repo.get_incident("inc_lifecycle_test")
    assert fetched.status == STATUS_RESOLVED
    assert fetched.resolved_at == "2026-09-05T16:45:00Z"


def test_resolve_nonexistent_incident_returns_none(mock_incidents_table):
    """Verify that attempting to resolve an unknown incident ID returns None without inserting."""
    repo = IncidentsRepository(
        table_name=TEST_INCIDENTS_TABLE,
        dynamodb_resource=mock_incidents_table,
    )
    result = repo.resolve_incident("inc_non_existent")
    assert result is None
