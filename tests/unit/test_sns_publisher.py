"""
Unit tests for the Amazon SNS Alert Publisher using Moto.
Tests publishing CRITICAL incident alerts, subject/message formatting,
graceful fallback on unconfigured topic ARN, and rejection of non-critical incidents.
"""
import boto3
import pytest
from moto import mock_aws

from backend.incidents.models import STATUS_OPEN, Incident
from backend.incidents.publisher import (
    SNSPublisher,
    format_alert_message,
    format_alert_subject,
)

TEST_REGION = "us-east-1"


@pytest.fixture
def mock_sns_topic():
    """Sets up an in-memory mock SNS topic for alerting tests."""
    with mock_aws():
        sns = boto3.client("sns", region_name=TEST_REGION)
        response = sns.create_topic(Name="cloudlog-critical-alerts-test")
        topic_arn = response["TopicArn"]
        yield {"client": sns, "topic_arn": topic_arn}


def build_test_incident(
    severity: str = "CRITICAL",
    service: str = "order-service",
    message: str = "Database connection pool exhausted",
    error_code: str = "DB_POOL_EXHAUSTED",
    incident_id: str = "inc_c49a10ef582103ba",
) -> Incident:
    """Helper to construct an Incident instance for publisher testing."""
    return Incident(
        incident_id=incident_id,
        service=service,
        severity=severity,
        status=STATUS_OPEN,
        message=message,
        source_event_id="evt_c49a10ef582103ba",
        source_s3_uri="s3://cloudlog-raw/2026/09/05/orders.jsonl",
        created_at="2026-09-05T14:30:00.000Z",
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# Formatting Unit Tests
# ---------------------------------------------------------------------------

def test_format_alert_subject():
    """Verify concise subject line formatting."""
    incident = build_test_incident(
        service="payment-service",
        message="Third-party gateway timeout after 5000ms",
    )
    subject = format_alert_subject(incident)
    assert subject.startswith("[CRITICAL ALERT] payment-service:")
    assert "Third-party gateway timeout" in subject
    assert len(subject) <= 100


def test_format_alert_subject_truncation():
    """Verify long messages are truncated with ellipsis in subject line."""
    very_long_message = "A" * 120
    incident = build_test_incident(service="auth-service", message=very_long_message)
    subject = format_alert_subject(incident)
    assert subject.endswith("...")
    assert len(subject) <= 100


def test_format_alert_message_content():
    """Verify all required operational fields are present in the notification body."""
    incident = build_test_incident(
        incident_id="inc_test_123",
        service="payment-service",
        message="Gateway unreachable",
        error_code="PGW_DOWN",
    )
    body = format_alert_message(incident)

    assert "CLOUDLOG CRITICAL INCIDENT ALERT" in body
    assert "inc_test_123" in body
    assert "payment-service" in body
    assert "CRITICAL" in body
    assert "OPEN" in body
    assert "Gateway unreachable" in body
    assert "PGW_DOWN" in body
    assert "evt_c49a10ef582103ba" in body
    assert "s3://cloudlog-raw/2026/09/05/orders.jsonl" in body
    assert "2026-09-05T14:30:00.000Z" in body


# ---------------------------------------------------------------------------
# Moto SNS Publisher Integration Tests
# ---------------------------------------------------------------------------

def test_critical_incident_publishes_successfully(mock_sns_topic):
    """Verify that a CRITICAL incident publishes successfully to the mock SNS topic."""
    topic_arn = mock_sns_topic["topic_arn"]
    client = mock_sns_topic["client"]

    publisher = SNSPublisher(topic_arn=topic_arn, sns_client=client)
    incident = build_test_incident(severity="CRITICAL")

    result = publisher.publish_critical_alert(incident)

    assert result.published is True
    assert result.message_id is not None
    assert len(result.message_id) > 0
    assert result.topic_arn == topic_arn
    assert "[CRITICAL ALERT]" in result.subject


def test_configured_topic_arn_is_used(mock_sns_topic):
    """Verify that the publisher targets the specific configured topic ARN."""
    topic_arn = mock_sns_topic["topic_arn"]
    client = mock_sns_topic["client"]

    publisher = SNSPublisher(topic_arn=topic_arn, sns_client=client)
    assert publisher.topic_arn == topic_arn

    incident = build_test_incident(severity="CRITICAL")
    result = publisher.publish_critical_alert(incident)

    assert result.topic_arn == topic_arn


def test_missing_topic_arn_skips_gracefully():
    """Verify that an empty or missing topic ARN logs a warning and skips without crashing."""
    publisher = SNSPublisher(topic_arn="")
    incident = build_test_incident(severity="CRITICAL")

    result = publisher.publish_critical_alert(incident)

    assert result.published is False
    assert result.message_id is None
    assert "not configured" in result.reason


def test_error_incident_is_not_published(mock_sns_topic):
    """Verify that an ERROR incident is rejected by the critical alert publisher."""
    topic_arn = mock_sns_topic["topic_arn"]
    client = mock_sns_topic["client"]

    publisher = SNSPublisher(topic_arn=topic_arn, sns_client=client)
    error_incident = build_test_incident(severity="ERROR")

    result = publisher.publish_critical_alert(error_incident)

    assert result.published is False
    assert result.message_id is None
    assert "not CRITICAL" in result.reason
