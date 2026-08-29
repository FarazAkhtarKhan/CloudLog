"""
Configuration and environment variable defaults for CloudLog.
"""
import os

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_EVENTS_TABLE = "cloudlog_events"
DEFAULT_INCIDENTS_TABLE = "cloudlog_incidents"

# Log Severity Classifications
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_SECURITY = "SECURITY"

VALID_SEVERITIES = {
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
    SEVERITY_CRITICAL,
    SEVERITY_SECURITY,
}


def get_aws_region() -> str:
    """Retrieve target AWS region."""
    return os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", DEFAULT_AWS_REGION))


def get_events_table_name() -> str:
    """Retrieve DynamoDB table name for log events."""
    return os.getenv("EVENTS_TABLE_NAME", DEFAULT_EVENTS_TABLE)


def get_incidents_table_name() -> str:
    """Retrieve DynamoDB table name for incidents."""
    return os.getenv("INCIDENTS_TABLE_NAME", DEFAULT_INCIDENTS_TABLE)


def get_sns_alert_topic_arn() -> str:
    """Retrieve SNS Topic ARN for critical alerts."""
    return os.getenv("SNS_ALERT_TOPIC_ARN", "")

