"""
Pytest configuration and shared test fixtures for CloudLog.
"""
import os
import pytest

# Ensure tests never hit real AWS credentials/resources
@pytest.fixture(autouse=True)
def aws_credentials_env():
    """Mock AWS Credentials for moto and local testing."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["EVENTS_TABLE_NAME"] = "cloudlog_events_test"
    os.environ["INCIDENTS_TABLE_NAME"] = "cloudlog_incidents_test"
