"""Shared fixtures. Every AWS call in the suite goes to moto's in-memory emulation."""
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from backend.local.resources import provision

REGION = "us-east-1"
NAMES = {
    "bucket": "cloudlog-test-raw",
    "events": "cloudlog_events_test",
    "incidents": "cloudlog_incidents_test",
    "runs": "cloudlog_runs_test",
    "topic": "cloudlog-alerts-test",
}


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION, "AWS_REGION": REGION,
        "EVENTS_TABLE_NAME": NAMES["events"], "INCIDENTS_TABLE_NAME": NAMES["incidents"],
        "RUNS_TABLE_NAME": NAMES["runs"], "S3_LOG_BUCKET": NAMES["bucket"],
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CLOUDLOG_LOCAL_MODE", raising=False)
    monkeypatch.delenv("SNS_ALERT_TOPIC_ARN", raising=False)


@pytest.fixture
def aws(monkeypatch):
    """Emulated account with the bucket, three tables, the topic and an SQS 'inbox' on the topic."""
    with mock_aws():
        handles = provision(REGION, NAMES)
        monkeypatch.setenv("SNS_ALERT_TOPIC_ARN", handles["topic_arn"])
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName="alert-inbox")["QueueUrl"]
        queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        handles["sns"].subscribe(TopicArn=handles["topic_arn"], Protocol="sqs", Endpoint=queue_arn)

        def inbox():
            messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
            return [json.loads(m["Body"]) for m in messages]

        yield SimpleNamespace(**handles, names=NAMES, inbox=inbox)


def jsonl(*lines) -> str:
    return "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n"


# Recent, so stored events fall inside the feed's look-back window (EVENT_TTL_DAYS) whenever the suite runs.
RECENT = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(level="INFO", service="order-service", message="Order created", ts=RECENT, **extra):
    return {"timestamp": ts, "service": service, "level": level, "message": message, **extra}

