"""
Unit tests for the S3 -> Lambda Ingestion Adapter using Moto.
Tests S3 event parsing, URL-key decoding, streaming ingestion, DynamoDB persistence,
and error handling without real AWS resources.
"""
import json
import urllib.parse
import boto3
import pytest
from moto import mock_aws

from backend.common.events_repository import EventsRepository
from backend.incidents.repository import IncidentsRepository
from backend.ingestion.handler import lambda_handler, process_s3_event

TEST_BUCKET = "cloudlog-raw-test"
TEST_TABLE = "cloudlog_events_test"
TEST_INCIDENTS_TABLE = "cloudlog_incidents_test"
TEST_REGION = "us-east-1"


@pytest.fixture
def mock_aws_env():
    """Sets up an in-memory mock S3, DynamoDB, and SNS environment for handler testing."""
    with mock_aws():
        # Setup S3 Bucket
        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)

        # Setup DynamoDB Events Table
        dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)
        events_table = dynamodb.create_table(
            TableName=TEST_TABLE,
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

        # Setup DynamoDB Incidents Table with GSI
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
                    "IndexName": "status-created_at-index",
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

        # Setup SNS Topic for critical alerts
        sns = boto3.client("sns", region_name=TEST_REGION)
        topic_res = sns.create_topic(Name="cloudlog-critical-alerts-test")
        topic_arn = topic_res["TopicArn"]
        import os
        os.environ["SNS_ALERT_TOPIC_ARN"] = topic_arn

        yield {
            "s3": s3,
            "dynamodb": dynamodb,
            "events_table": events_table,
            "incidents_table": incidents_table,
            "sns": sns,
            "topic_arn": topic_arn,
        }


def build_s3_event(bucket_name: str, object_key: str, url_encode: bool = False) -> dict:
    """Construct an AWS S3 ObjectCreated event notification dictionary."""
    key_field = urllib.parse.quote_plus(object_key) if url_encode else object_key
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": bucket_name},
                    "object": {"key": key_field},
                },
            }
        ]
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_valid_s3_event_end_to_end(mock_aws_env):
    """Verify full end-to-end flow: S3 event -> Lambda -> Ingestion -> DynamoDB."""
    s3 = mock_aws_env["s3"]
    key = "2026/09/05/auth.jsonl"
    content = (
        '{"timestamp": "2026-09-05T10:00:00.000Z", "service": "auth-service", "level": "INFO", "message": "Login success"}\n'
    )
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=content.encode("utf-8"))

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["processed_files"] == 1
    assert body["total_lines"] == 1
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 0

    # Verify event was saved to DynamoDB
    repo = EventsRepository(table_name=TEST_TABLE)
    saved_events = repo.get_events_by_service("auth-service")
    assert len(saved_events) == 1
    assert saved_events[0].service == "auth-service"
    assert saved_events[0].message == "Login success"
    assert saved_events[0].level == "INFO"


def test_multiple_records_in_one_file(mock_aws_env):
    """Verify processing multiple log records from a single S3 JSONL file."""
    s3 = mock_aws_env["s3"]
    key = "logs/payments.jsonl"
    records = [
        {"timestamp": "2026-09-05T10:01:00Z", "service": "payment-service", "level": "INFO", "message": "Tx 1 initiated"},
        {"timestamp": "2026-09-05T10:02:00Z", "service": "payment-service", "level": "WARNING", "message": "Tx 2 slow"},
        {"timestamp": "2026-09-05T10:03:00Z", "service": "payment-service", "level": "ERROR", "message": "Tx 3 failed", "error_code": "TX_ERR"},
    ]
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=content.encode("utf-8"))

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total_lines"] == 3
    assert body["valid_count"] == 3
    assert body["invalid_count"] == 0

    # Verify all 3 records were written to DynamoDB
    repo = EventsRepository(table_name=TEST_TABLE)
    events = repo.get_events_by_service("payment-service")
    assert len(events) == 3


def test_mixture_of_valid_and_invalid_lines(mock_aws_env):
    """Verify that a corrupted line does not stop ingestion of valid lines."""
    s3 = mock_aws_env["s3"]
    key = "logs/mixed.jsonl"
    content = (
        '{"timestamp": "2026-09-05T11:00:00Z", "service": "order-service", "level": "INFO", "message": "Valid 1"}\n'
        'THIS IS CORRUPTED NOT JSON\n'
        '{"timestamp": "2026-09-05T11:02:00Z", "service": "order-service", "level": "CRITICAL", "message": "Valid 3"}\n'
    )
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=content.encode("utf-8"))

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total_lines"] == 3
    assert body["valid_count"] == 2
    assert body["invalid_count"] == 1

    # Valid records must be saved in DynamoDB
    repo = EventsRepository(table_name=TEST_TABLE)
    events = repo.get_events_by_service("order-service")
    assert len(events) == 2


def test_url_encoded_s3_object_key(mock_aws_env):
    """Verify S3 keys containing spaces or special characters are decoded properly."""
    s3 = mock_aws_env["s3"]
    real_key = "production logs/app+service/debug=true.jsonl"
    content = (
        '{"timestamp": "2026-09-05T12:00:00Z", "service": "web-service", "level": "INFO", "message": "Key test"}\n'
    )
    s3.put_object(Bucket=TEST_BUCKET, Key=real_key, Body=content.encode("utf-8"))

    # S3 sends URL-encoded key in the event notification
    event = build_s3_event(TEST_BUCKET, real_key, url_encode=True)
    # The event record key will look like "production+logs%2Fapp%2Bservice%2Fdebug%3Dtrue.jsonl"
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["valid_count"] == 1

    repo = EventsRepository(table_name=TEST_TABLE)
    events = repo.get_events_by_service("web-service")
    assert len(events) == 1
    assert events[0].source_s3_uri == f"s3://{TEST_BUCKET}/{real_key}"


def test_missing_records_in_event(mock_aws_env):
    """Verify handling when an event has missing or empty Records."""
    response_empty = lambda_handler({})
    assert response_empty["statusCode"] == 400

    response_no_records = lambda_handler({"Records": []})
    assert response_no_records["statusCode"] == 400


def test_s3_object_not_found(mock_aws_env):
    """Verify graceful 404 response when the referenced S3 key does not exist."""
    event = build_s3_event(TEST_BUCKET, "nonexistent/file.jsonl")
    response = lambda_handler(event)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert "S3 retrieval failure" in body["error"]


def test_empty_s3_file(mock_aws_env):
    """Verify processing an empty file completes safely with zero events."""
    s3 = mock_aws_env["s3"]
    key = "logs/empty.jsonl"
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=b"")

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total_lines"] == 0
    assert body["valid_count"] == 0
    assert body["invalid_count"] == 0


def test_dynamodb_persistence_verification(mock_aws_env):
    """Verify that multiple services in one file are indexed under distinct partition keys."""
    s3 = mock_aws_env["s3"]
    key = "logs/multi_service.jsonl"
    content = (
        '{"timestamp": "2026-09-05T13:00:00Z", "service": "service-A", "level": "INFO", "message": "msg A"}\n'
        '{"timestamp": "2026-09-05T13:00:01Z", "service": "service-B", "level": "ERROR", "message": "msg B"}\n'
    )
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=content.encode("utf-8"))

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)
    assert response["statusCode"] == 200

    repo = EventsRepository(table_name=TEST_TABLE)
    events_a = repo.get_events_by_service("service-A")
    events_b = repo.get_events_by_service("service-B")

    assert len(events_a) == 1
    assert events_a[0].message == "msg A"
    assert len(events_b) == 1
    assert events_b[0].message == "msg B"


def test_error_and_critical_create_incidents_end_to_end(mock_aws_env):
    """Verify that ERROR and CRITICAL events create incidents and trigger SNS alerts."""
    s3 = mock_aws_env["s3"]
    key = "logs/incidents_flow.jsonl"
    content = (
        '{"timestamp": "2026-09-05T14:00:00Z", "service": "auth-service", "level": "INFO", "message": "User login"}\n'
        '{"timestamp": "2026-09-05T14:01:00Z", "service": "payment-service", "level": "ERROR", "message": "Gateway timeout", "error_code": "PGW_504"}\n'
        '{"timestamp": "2026-09-05T14:02:00Z", "service": "database-service", "level": "CRITICAL", "message": "Connection pool exhausted", "error_code": "DB_EXH"}\n'
    )
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=content.encode("utf-8"))

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total_lines"] == 3
    assert body["valid_count"] == 3
    assert body["incidents_count"] == 2
    assert body["alerts_count"] == 1

    # Verify incidents in DynamoDB
    inc_repo = IncidentsRepository(table_name=TEST_INCIDENTS_TABLE)
    open_incidents = inc_repo.get_open_incidents()
    assert len(open_incidents) == 2

    # Check that error incident was created
    error_inc = next(i for i in open_incidents if i.service == "payment-service")
    assert error_inc.severity == "ERROR"
    assert error_inc.status == "OPEN"
    assert error_inc.message == "Gateway timeout"
    assert error_inc.error_code == "PGW_504"

    # Check that critical incident was created
    crit_inc = next(i for i in open_incidents if i.service == "database-service")
    assert crit_inc.severity == "CRITICAL"
    assert crit_inc.status == "OPEN"
    assert crit_inc.message == "Connection pool exhausted"
    assert crit_inc.error_code == "DB_EXH"


def test_info_warning_do_not_create_incidents(mock_aws_env):
    """Verify that INFO and WARNING logs do not create any records in the incidents table."""
    s3 = mock_aws_env["s3"]
    key = "logs/no_incidents.jsonl"
    content = (
        '{"timestamp": "2026-09-05T15:00:00Z", "service": "frontend", "level": "INFO", "message": "Page viewed"}\n'
        '{"timestamp": "2026-09-05T15:01:00Z", "service": "frontend", "level": "WARNING", "message": "Slow render"}\n'
    )
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=content.encode("utf-8"))

    event = build_s3_event(TEST_BUCKET, key)
    response = lambda_handler(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["incidents_count"] == 0
    assert body["alerts_count"] == 0

    inc_repo = IncidentsRepository(table_name=TEST_INCIDENTS_TABLE)
    assert len(inc_repo.get_open_incidents()) == 0

