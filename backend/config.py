"""
Central configuration for CloudLog.

Every AWS resource name is read from an environment variable that Terraform
sets on the Lambda functions (and the local emulator sets for offline runs).
"""
import os

# --- Log severities ---------------------------------------------------------
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"
CRITICAL = "CRITICAL"
SEVERITIES = (INFO, WARNING, ERROR, CRITICAL)  # ordered low -> high
SEVERITY_RANK = {level: rank for rank, level in enumerate(SEVERITIES)}

# --- Incident lifecycle -----------------------------------------------------
OPEN = "OPEN"
ACKNOWLEDGED = "ACKNOWLEDGED"
RESOLVED = "RESOLVED"
INCIDENT_STATUSES = (OPEN, ACKNOWLEDGED, RESOLVED)
ACTIVE_STATUSES = (OPEN, ACKNOWLEDGED)

# --- Detection tuning -------------------------------------------------------
WARNING_BURST_THRESHOLD = 3     # same warning N times in one batch -> incident
BRUTE_FORCE_THRESHOLD = 5       # N failed logins from one IP in one batch -> incident
ESCALATION_THRESHOLD = 5        # ERROR incident seen N times in total -> CRITICAL
AUTH_FAILURE_CODES = {"AUTH_LOGIN_FAILED", "AUTH_INVALID_TOKEN", "AUTH_MFA_FAILED"}

# --- Data lifecycle (DynamoDB TTL) -----------------------------------------
EVENT_TTL_DAYS = 7
RUN_TTL_DAYS = 3

# --- Pipeline -----------------------------------------------------------------
PIPELINE_STAGE = "processor"          # partition key of the pipeline-runs table
SIMULATION_PREFIX = "raw-logs/simulations/"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def aws_region() -> str:
    return os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-south-1"))


def events_table() -> str:
    return env("EVENTS_TABLE_NAME", "cloudlog_events")


def incidents_table() -> str:
    return env("INCIDENTS_TABLE_NAME", "cloudlog_incidents")


def runs_table() -> str:
    return env("RUNS_TABLE_NAME", "cloudlog_pipeline_runs")


def log_bucket() -> str:
    return env("S3_LOG_BUCKET")


def alert_topic_arn() -> str:
    return env("SNS_ALERT_TOPIC_ARN")


def local_mode() -> bool:
    """True only inside the offline emulator; enables the X-User-Role dev header."""
    return env("CLOUDLOG_LOCAL_MODE") == "1"
