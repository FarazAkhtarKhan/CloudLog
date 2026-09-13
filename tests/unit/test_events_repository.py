"""
Unit tests for the DynamoDB EventsRepository using Moto.
Tests table creation, item persistence, retrieval, queries, and idempotency.
"""
import boto3
import pytest
from moto import mock_aws

from backend.analyzer.models import LogEvent
from backend.common.events_repository import EventsRepository

TEST_TABLE_NAME = "cloudlog_events_test"
TEST_REGION = "us-east-1"


@pytest.fixture
def mock_dynamodb():
    """Sets up an in-memory mock DynamoDB environment with the cloudlog_events table."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = dynamodb.create_table(
            TableName=TEST_TABLE_NAME,
            KeySchema=[
                {"AttributeName": "service", "KeyType": "HASH"},
                {"AttributeName": "sort_key", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "service", "AttributeType": "S"},
                {"AttributeName": "sort_key", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield dynamodb


def build_test_event(
    service: str = "auth-service",
    timestamp: str = "2026-09-05T10:00:00.000Z",
    event_id: str = "evt_a1b2c3d4e5f67890",
    level: str = "INFO",
    message: str = "User authenticated successfully",
    line_number: int = 1,
    error_code: str = None,
    endpoint: str = None,
    ip_address: str = None,
) -> LogEvent:
    """Helper to construct a fully formed LogEvent for repository testing."""
    return LogEvent(
        event_id=event_id,
        service=service,
        timestamp=timestamp,
        sort_key=f"{timestamp}#{event_id}",
        level=level,
        message=message,
        source_s3_uri="s3://cloudlog-raw/2026/09/05/logs.jsonl",
        line_number=line_number,
        processed_at="2026-09-05T10:00:00.500Z",
        is_incident=(level in {"ERROR", "CRITICAL"}),
        requires_alert=(level == "CRITICAL"),
        error_code=error_code,
        endpoint=endpoint,
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_table_setup_and_repository_init(mock_dynamodb):
    """Verify repository initializes and connects to the mock DynamoDB table."""
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)
    assert repo.table_name == TEST_TABLE_NAME
    assert repo._table.table_status == "ACTIVE"


def test_save_and_retrieve_single_event(mock_dynamodb):
    """Verify saving a valid LogEvent and retrieving it by primary key."""
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)

    event = build_test_event(
        service="payment-service",
        timestamp="2026-09-05T14:30:00.123Z",
        event_id="evt_pay_000000001",
        level="ERROR",
        message="Payment timeout on gateway",
        error_code="PGW_504",
        endpoint="/api/v1/checkout",
        ip_address="192.168.1.100",
    )

    repo.save_event(event)

    retrieved = repo.get_event(service="payment-service", sort_key=event.sort_key)

    assert retrieved is not None
    assert retrieved.service == "payment-service"
    assert retrieved.sort_key == event.sort_key
    assert retrieved.event_id == "evt_pay_000000001"
    assert retrieved.level == "ERROR"
    assert retrieved.message == "Payment timeout on gateway"
    assert retrieved.error_code == "PGW_504"
    assert retrieved.endpoint == "/api/v1/checkout"
    assert retrieved.ip_address == "192.168.1.100"
    assert retrieved.line_number == 1
    assert retrieved.is_incident is True
    assert retrieved.requires_alert is False


def test_get_nonexistent_event(mock_dynamodb):
    """Verify that querying a non-existent primary key returns None."""
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)
    retrieved = repo.get_event(service="unknown-service", sort_key="2026-09-05T00:00:00Z#evt_none")
    assert retrieved is None


def test_multiple_events_for_same_service(mock_dynamodb):
    """Verify querying multiple events belonging to the same partition key."""
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)

    event1 = build_test_event(
        service="order-service",
        timestamp="2026-09-05T10:00:00.000Z",
        event_id="evt_ord_000000001",
        level="INFO",
        message="Order created",
    )
    event2 = build_test_event(
        service="order-service",
        timestamp="2026-09-05T10:05:00.000Z",
        event_id="evt_ord_000000002",
        level="WARNING",
        message="Order stock low",
    )
    event3 = build_test_event(
        service="order-service",
        timestamp="2026-09-05T10:10:00.000Z",
        event_id="evt_ord_000000003",
        level="CRITICAL",
        message="Order DB deadlocked",
    )

    repo.save_event(event1)
    repo.save_event(event2)
    repo.save_event(event3)

    # Query descending (newest first, scan_forward=False)
    results_desc = repo.get_events_by_service(service="order-service", scan_forward=False)
    assert len(results_desc) == 3
    assert results_desc[0].event_id == "evt_ord_000000003"
    assert results_desc[1].event_id == "evt_ord_000000002"
    assert results_desc[2].event_id == "evt_ord_000000001"

    # Query ascending (chronological, scan_forward=True)
    results_asc = repo.get_events_by_service(service="order-service", scan_forward=True)
    assert len(results_asc) == 3
    assert results_asc[0].event_id == "evt_ord_000000001"
    assert results_asc[2].event_id == "evt_ord_000000003"


def test_events_isolated_by_service_partition(mock_dynamodb):
    """Verify that queries for service A do not return events from service B."""
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)

    event_auth = build_test_event(service="auth-service", event_id="evt_auth_1")
    event_pay = build_test_event(service="payment-service", event_id="evt_pay_1")

    repo.save_event(event_auth)
    repo.save_event(event_pay)

    auth_events = repo.get_events_by_service(service="auth-service")
    assert len(auth_events) == 1
    assert auth_events[0].service == "auth-service"

    pay_events = repo.get_events_by_service(service="payment-service")
    assert len(pay_events) == 1
    assert pay_events[0].service == "payment-service"


def test_idempotent_save_does_not_create_duplicates(mock_dynamodb):
    """
    Verify that saving the exact same event twice (e.g. during a Lambda retry)
    overwrites the record idempotently rather than duplicating it.
    """
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)

    event = build_test_event(
        service="notification-service",
        timestamp="2026-09-05T12:00:00.000Z",
        event_id="evt_notif_retry_1",
        level="INFO",
        message="Initial write",
    )

    # First save
    repo.save_event(event)
    events_after_first_save = repo.get_events_by_service(service="notification-service")
    assert len(events_after_first_save) == 1
    assert events_after_first_save[0].message == "Initial write"

    # Simulate retry with updated message on same PK & SK
    event_retry = build_test_event(
        service="notification-service",
        timestamp="2026-09-05T12:00:00.000Z",
        event_id="evt_notif_retry_1",  # Same deterministic ID
        level="INFO",
        message="Retried write with identical keys",
    )

    repo.save_event(event_retry)
    events_after_second_save = repo.get_events_by_service(service="notification-service")

    # Table item count MUST still be 1 (idempotent overwrite)
    assert len(events_after_second_save) == 1
    assert events_after_second_save[0].message == "Retried write with identical keys"


def test_batch_save_events(mock_dynamodb):
    """Verify batch saving multiple events via batch_writer."""
    repo = EventsRepository(table_name=TEST_TABLE_NAME, dynamodb_resource=mock_dynamodb)

    events = [
        build_test_event(service="worker-service", event_id=f"evt_batch_{i}", line_number=i)
        for i in range(1, 6)
    ]

    saved_count = repo.save_events(events)
    assert saved_count == 5

    stored = repo.get_events_by_service(service="worker-service")
    assert len(stored) == 5
