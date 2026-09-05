"""
Unit tests for the CloudLog REST API Lambda handler and RBAC authorization using Moto.
Tests all endpoints: /events, /events/critical, /incidents, /incidents/{id}, /statistics, /services,
as well as role-based permissions (Admin, Analyst, Viewer).
"""
import json
import boto3
import pytest
from moto import mock_aws

from backend.analyzer.models import LogEvent
from backend.api.handler import handle_api_request, lambda_handler
from backend.common.events_repository import EventsRepository
from backend.incidents.models import (
    INCIDENT_INDEX_NAME,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Incident,
)
from backend.incidents.repository import IncidentsRepository

TEST_EVENTS_TABLE = "cloudlog_events_test"
TEST_INCIDENTS_TABLE = "cloudlog_incidents_test"
TEST_REGION = "us-east-1"


@pytest.fixture
def mock_api_env():
    """Sets up in-memory DynamoDB tables with test data for API testing."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)

        # 1. Events Table
        events_table = dynamodb.create_table(
            TableName=TEST_EVENTS_TABLE,
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
        events_table.wait_until_exists()

        # 2. Incidents Table
        incidents_table = dynamodb.create_table(
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
        incidents_table.wait_until_exists()

        events_repo = EventsRepository(table_name=TEST_EVENTS_TABLE, dynamodb_resource=dynamodb)
        incidents_repo = IncidentsRepository(table_name=TEST_INCIDENTS_TABLE, dynamodb_resource=dynamodb)

        # Seed sample events
        e1 = LogEvent(
            event_id="evt_001",
            service="auth-service",
            timestamp="2026-09-05T10:00:00Z",
            sort_key="2026-09-05T10:00:00Z#evt_001",
            level="INFO",
            message="User login",
            source_s3_uri="s3://b/k",
            line_number=1,
            processed_at="2026-09-05T10:00:01Z",
            is_incident=False,
            requires_alert=False,
        )
        e2 = LogEvent(
            event_id="evt_002",
            service="payment-service",
            timestamp="2026-09-05T10:05:00Z",
            sort_key="2026-09-05T10:05:00Z#evt_002",
            level="ERROR",
            message="Payment gateway 504",
            source_s3_uri="s3://b/k",
            line_number=2,
            processed_at="2026-09-05T10:05:01Z",
            is_incident=True,
            requires_alert=False,
            error_code="PGW_504",
        )
        e3 = LogEvent(
            event_id="evt_003",
            service="order-service",
            timestamp="2026-09-05T10:10:00Z",
            sort_key="2026-09-05T10:10:00Z#evt_003",
            level="CRITICAL",
            message="Order DB connection failure",
            source_s3_uri="s3://b/k",
            line_number=3,
            processed_at="2026-09-05T10:10:01Z",
            is_incident=True,
            requires_alert=True,
            error_code="DB_CONN_ERR",
        )
        events_repo.save_events([e1, e2, e3])

        # Seed sample incidents
        inc1 = Incident(
            incident_id="inc_002",
            service="payment-service",
            severity="ERROR",
            status=STATUS_OPEN,
            message="Payment gateway 504",
            source_event_id="evt_002",
            source_s3_uri="s3://b/k",
            created_at="2026-09-05T10:05:00Z",
            error_code="PGW_504",
        )
        inc2 = Incident(
            incident_id="inc_003",
            service="order-service",
            severity="CRITICAL",
            status=STATUS_OPEN,
            message="Order DB connection failure",
            source_event_id="evt_003",
            source_s3_uri="s3://b/k",
            created_at="2026-09-05T10:10:00Z",
            error_code="DB_CONN_ERR",
        )
        incidents_repo.save_incident(inc1)
        incidents_repo.save_incident(inc2)

        yield {
            "dynamodb": dynamodb,
            "events_repo": events_repo,
            "incidents_repo": incidents_repo,
        }


def make_api_event(
    path: str,
    method: str = "GET",
    query_params: dict = None,
    path_params: dict = None,
    body: dict = None,
    role: str = "Viewer",
) -> dict:
    """Helper creating an API Gateway HTTP API v2 proxy payload."""
    return {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
            },
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": f"user-{role.lower()}",
                        "email": f"{role.lower()}@cloudlog.local",
                        "cognito:groups": [role],
                    }
                }
            },
        },
        "queryStringParameters": query_params or {},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
        "headers": {
            "content-type": "application/json",
            "x-user-role": role,
        },
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_get_statistics(mock_api_env):
    """Verify GET /statistics returns aggregated counts and breakdown."""
    event = make_api_event("/statistics")
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total_events"] == 3
    assert body["error_count"] == 1
    assert body["critical_count"] == 1
    assert body["open_incidents_count"] == 2
    assert "severity_counts" in body
    assert body["severity_counts"]["INFO"] == 1
    assert body["severity_counts"]["ERROR"] == 1
    assert body["severity_counts"]["CRITICAL"] == 1


def test_get_services(mock_api_env):
    """Verify GET /services returns distinct microservice names."""
    event = make_api_event("/services")
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["count"] == 3
    assert set(body["services"]) == {"auth-service", "payment-service", "order-service"}


def test_get_events(mock_api_env):
    """Verify GET /events returns log events."""
    event = make_api_event("/events")
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["count"] == 3
    assert len(body["events"]) == 3


def test_get_critical_events(mock_api_env):
    """Verify GET /events/critical filters strictly to CRITICAL events."""
    event = make_api_event("/events/critical")
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["count"] == 1
    assert body["events"][0]["level"] == "CRITICAL"
    assert body["events"][0]["service"] == "order-service"


def test_get_incidents(mock_api_env):
    """Verify GET /incidents returns open incidents."""
    event = make_api_event("/incidents", query_params={"status": "OPEN"})
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["count"] == 2


def test_get_single_incident(mock_api_env):
    """Verify GET /incidents/{id} returns single incident."""
    event = make_api_event("/incidents/inc_002", path_params={"id": "inc_002"})
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["incident"]["incident_id"] == "inc_002"
    assert body["incident"]["service"] == "payment-service"


def test_get_unknown_incident_returns_404(mock_api_env):
    """Verify GET /incidents/unknown returns 404."""
    event = make_api_event("/incidents/inc_nonexistent", path_params={"id": "inc_nonexistent"})
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 404


def test_viewer_cannot_resolve_incident(mock_api_env):
    """Verify that a user with Viewer role receives 403 when attempting PATCH /incidents/{id}."""
    event = make_api_event(
        path="/incidents/inc_002",
        method="PATCH",
        path_params={"id": "inc_002"},
        body={"status": "RESOLVED"},
        role="Viewer",
    )
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert "Forbidden" in body["error"]


def test_analyst_can_resolve_incident(mock_api_env):
    """Verify that an Analyst role successfully resolves an incident."""
    event = make_api_event(
        path="/incidents/inc_002",
        method="PATCH",
        path_params={"id": "inc_002"},
        body={"status": "RESOLVED"},
        role="Analyst",
    )
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["incident"]["status"] == "RESOLVED"
    assert body["incident"]["resolved_at"] is not None


def test_admin_can_resolve_incident(mock_api_env):
    """Verify that an Admin role successfully resolves an incident."""
    event = make_api_event(
        path="/incidents/inc_003",
        method="PATCH",
        path_params={"id": "inc_003"},
        body={"status": "RESOLVED"},
        role="Admin",
    )
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["incident"]["status"] == "RESOLVED"


def test_cors_preflight(mock_api_env):
    """Verify OPTIONS request returns 200 with CORS headers."""
    event = make_api_event("/statistics", method="OPTIONS")
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 200
    assert response["headers"]["Access-Control-Allow-Origin"] == "*"


def test_unknown_route_returns_404(mock_api_env):
    """Verify unmapped routes return 404 with list of available endpoints."""
    event = make_api_event("/unsupported/route")
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert "available_endpoints" in body


@mock_aws
def test_simulate_log_success(mock_api_env, monkeypatch):
    """Verify POST /simulate uploads a log to S3 for Admin/Analyst."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-log-bucket")
    monkeypatch.setenv("S3_LOG_BUCKET", "test-log-bucket")

    event = make_api_event(
        "/simulate",
        method="POST",
        body={"service": "checkout-service", "level": "CRITICAL", "message": "Checkout crashed"},
        role="Analyst",
    )
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert "s3_uri" in body
    assert body["log"]["service"] == "checkout-service"
    assert body["log"]["level"] == "CRITICAL"


def test_simulate_log_viewer_forbidden(mock_api_env):
    """Verify POST /simulate returns 403 for Viewer role."""
    event = make_api_event(
        "/simulate",
        method="POST",
        body={"service": "checkout-service", "level": "CRITICAL"},
        role="Viewer",
    )
    response = handle_api_request(
        event,
        events_repo=mock_api_env["events_repo"],
        incidents_repo=mock_api_env["incidents_repo"],
    )

    assert response["statusCode"] == 403

