# CloudLog

CloudLog is an event-driven log processing and automated incident detection pipeline built with AWS serverless services. It ingests structured application logs uploaded to Amazon S3, parses and validates them via AWS Lambda, indexes events in DynamoDB, and dispatches real-time alerts via Amazon SNS when high-severity anomalies or failures are detected.

---

## Why CloudLog?

Managing dedicated logging clusters (like Elasticsearch or OpenSearch) introduces ongoing infrastructure costs, cluster management overhead, and capacity planning. 

CloudLog provides a lightweight, cost-effective alternative for cloud-native applications:
- **Zero Idle Cost**: Built purely on serverless components (S3, Lambda, DynamoDB, SNS).
- **Automated Incident Tracking**: Automatically separates raw telemetry from actionable operational/security incidents.
- **Immediate Escalation**: Sends instant push notifications for critical errors and security anomalies.
- **Fast Offline Development**: Includes an in-memory test suite powered by `moto`, enabling offline testing without cloud credentials or heavy emulator containers.

---

## Architecture

```text
                        ┌─────────────────────────────────────────┐
                        │      Application / Microservices        │
                        └────────────────────┬────────────────────┘
                                             │ (Writes .json / .jsonl)
                                             ▼
                                  ┌────────────────────┐
                                  │  Amazon S3 Bucket  │
                                  │   (Log Storage)    │
                                  └──────────┬─────────┘
                                             │ (ObjectCreated Notification)
                                             ▼
                                  ┌────────────────────┐
                                  │     AWS Lambda     │
                                  │  (Log Processor)   │
                                  └──────────┬─────────┘
                                             │
                   ┌─────────────────────────┼─────────────────────────┐
                   │                         │                         │
                   ▼                         ▼                         ▼
        ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
        │  DynamoDB (Events)  │   │DynamoDB (Incidents) │   │     Amazon SNS      │
        │   cloudlog_events   │   │  cloudlog_incidents │   │   (Critical Topic)  │
        │  (All parsed logs)  │   │  (Errors/Critical)  │   │ (Email/SMS Alerts)  │
        └─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

For complete architectural decisions, data access patterns, and failure strategies, see [docs/architecture.md](docs/architecture.md).

---

## Repository Structure

```text
CloudLog/
├── backend/
│   ├── common/              # Shared configs, constants, and utilities
│   ├── ingestion/           # S3 event listener and payload extraction
│   ├── analyzer/            # Log schema validation, parsing, and classification
│   ├── incidents/           # Incident creation and lifecycle management
│   └── api/                 # API handlers for querying logs & incidents
├── infrastructure/
│   └── terraform/           # Terraform IaC for S3, DynamoDB, Lambda, SNS, IAM
├── tests/
│   ├── unit/                # Fast unit and integration tests (using moto)
│   └── fixtures/            # Sample log payloads and S3 test events
├── docs/
│   └── architecture.md      # System design, data models, and ADRs
├── docker/                  # Docker configs (e.g., synthetic log generator)
├── pyproject.toml           # Tooling & pytest configurations
├── requirements.txt         # Runtime dependencies (boto3)
└── requirements-dev.txt     # Development and testing dependencies (pytest, moto, ruff)
```

---

## Log Schema Specification

Services write logs as JSON objects or newline-delimited JSON (`.jsonl`). Each record follows this standard contract:

```json
{
  "timestamp": "2026-08-25T14:31:05.412Z",
  "service_name": "payment-service",
  "log_level": "ERROR",
  "message": "Payment transaction failed due to third-party timeout",
  "error_code": "PGW_TIMEOUT_504",
  "ip_address": "192.168.1.15",
  "endpoint": "/api/v1/payments/process",
  "metadata": {
    "transaction_id": "tx_998124",
    "retry_count": 3
  }
}
```

### Severity Classification

| Level | Description | Destination | Alert Triggered |
| :--- | :--- | :--- | :--- |
| `INFO` | Routine operational messages | `cloudlog_events` | No |
| `WARNING` | Degraded performance / elevated latencies | `cloudlog_events` | No |
| `ERROR` | Recoverable application errors & exceptions | `cloudlog_events`, `cloudlog_incidents` | No |
| `CRITICAL` | Unreachable dependencies, database outages | `cloudlog_events`, `cloudlog_incidents` | **Yes (SNS)** |
| `SECURITY` | Unauthorized access attempts, brute force patterns | `cloudlog_events`, `cloudlog_incidents` | **Yes (SNS)** |

---

## Getting Started

### Prerequisites
- Python 3.11+
- Git

### 1. Setup Local Environment

```bash
# Clone the repository (if not already local)
git clone git@github.com:FarazAkhtarKhan/CloudLog.git
cd CloudLog

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt
```

### 2. Run Tests

The test suite runs completely offline with mocked AWS services:

```bash
pytest
```

To run linting and style checks:

```bash
ruff check .
```

---

## Configuration

CloudLog components are configured using standard environment variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `AWS_REGION` | AWS target region | `us-east-1` |
| `EVENTS_TABLE_NAME` | DynamoDB table for all log events | `cloudlog_events` |
| `INCIDENTS_TABLE_NAME` | DynamoDB table for incidents | `cloudlog_incidents` |
| `SNS_ALERT_TOPIC_ARN` | SNS topic ARN for critical alert notifications | `""` |

---

## License

This project is licensed under the MIT License.
