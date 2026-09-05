# CloudLog

> **Serverless Critical Log Analysis and Incident Detection System**

CloudLog is an event-driven, production-grade cloud telemetry pipeline and operational incident management dashboard built entirely on AWS serverless services. Designed for modern microservice architectures, CloudLog replaces heavy, expensive logging clusters (e.g. Elasticsearch/OpenSearch) with a zero-idle-cost serverless architecture that ingests structured application logs, extracts deterministic event telemetry, detects high-severity incidents in real time, publishes instant notifications via Amazon SNS, and provides an authenticated Single Page Application (SPA) dashboard backed by AWS Cognito and Amazon API Gateway.

---

## Key Features

- **Zero Idle Infrastructure Cost:** Built 100% on AWS Free Tier serverless primitives (S3, Lambda, DynamoDB, API Gateway HTTP API, Cognito, SNS, CloudWatch).
- **Deterministic Event Idempotency:** Derives unique SHA-256 event fingerprints (`evt_<hash>`) based on S3 object keys and line offsets, guaranteeing safe at-least-once execution and zero duplicate records across Lambda retries.
- **Automated Incident Escalation:** Segregates routine application telemetry (`INFO`, `WARNING`) from actionable incidents (`ERROR`, `CRITICAL`), dispatching immediate push notifications for critical outages while tracking incident lifecycles (`OPEN` $\rightarrow$ `RESOLVED`).
- **Role-Based Access Control (RBAC):** Cognito User Pools enforce granular role hierarchies (`Admin`, `Analyst`, `Viewer`) validated via native API Gateway JWT authorizers and Lambda security policies.
- **Modern Operations Dashboard:** React 19 + Vite dashboard featuring dark-mode glassmorphic aesthetics, live 10-second polling, interactive incident queue, and system-wide telemetry distribution breakdowns.
- **Offline Development & In-Memory Testing:** 68 comprehensive unit and integration tests executing with `pytest` and `moto` in under 4 seconds without cloud credentials or heavy Docker emulator overhead.
- **Production IaC Automation:** Flat, declarative Terraform architecture for reproducible provisioning, live verification, and 1-command zero-residual billing teardown (`terraform destroy`).

---

## System Architecture

```text
[Application / Microservices]
             │
             ▼ (PutObject .jsonl batch)
     [Amazon S3 Bucket]
             │
             ▼ (s3:ObjectCreated:* Notification)
     [AWS Lambda: Log Processor]
             │
             ├──► [Ingestion: S3 Line Stream & Validation]
             ├──► [Analyzer: Deterministic Hashing & Severity Classification]
             │
             ├──► [DynamoDB: cloudlog_events Table (All Validated Events)]
             │
             ├──► [DynamoDB: cloudlog_incidents Table (ERROR / CRITICAL)]
             │
             └──► [Amazon SNS Topic (CRITICAL Outage Alerts Only)]

[React 19 Dashboard] ──(USER_PASSWORD_AUTH)──► [AWS Cognito User Pool]
         │                                              │
         │ (Authorization: Bearer <IdToken>)            ▼ (JWT Claims)
         ▼
[API Gateway HTTP API v2] ────(JWT Authorizer)────► [AWS Lambda: API Handler]
                                                              │
                                                              ▼
                                                    [DynamoDB Dual-Table]
```

For complete architectural decisions, data models, and ADR records, see [docs/architecture.md](docs/architecture.md).

---

## Repository Structure

```text
CloudLog/
├── backend/
│   ├── common/              # Configs, constants, and DynamoDB EventsRepository
│   ├── ingestion/           # Streaming S3 JSONL reader and Lambda event handler
│   ├── analyzer/            # Schema validation, models, and deterministic event ID generator
│   ├── incidents/           # Incident models, IncidentsRepository (GSI), and SNSPublisher
│   └── api/                 # API Lambda controller and Cognito RBAC claims evaluator
├── frontend/                # React 19 + Vite dashboard SPA with dark-mode glassmorphism
│   ├── src/
│   │   ├── services/        # Cognito auth client and authenticated API Gateway fetcher
│   │   ├── config.js        # AWS endpoints, client IDs, and demo user accounts
│   │   ├── App.jsx          # Live incident queue, telemetry stream, and KPI cards
│   │   └── App.css          # Glassmorphic responsive styling
├── infrastructure/
│   └── terraform/           # Flat Terraform IaC (S3, DynamoDB, Lambda, SNS, Cognito, API GW)
├── scripts/
│   ├── generate_sample_logs.py  # Realistic multi-service JSONL log generator & S3 uploader
│   └── test_e2e_aws.py          # Automated live AWS integration test suite
├── tests/
│   ├── unit/                # 68 unit tests for analyzer, ingestion, incidents, SNS, and API
│   └── fixtures/            # Sample valid and malformed log files
├── docs/
│   └── architecture.md      # Comprehensive architecture specifications & ADRs
└── .github/workflows/
    └── ci.yml               # GitHub Actions CI pipeline (Python tests, frontend build, Terraform check)
```

---

## Log Ingestion Contract

Applications deliver logs as JSON Lines (`.jsonl`) to Amazon S3. Each line contains a self-contained JSON object conforming to the CloudLog contract:

```json
{
  "timestamp": "2026-09-05T18:20:00.123Z",
  "service": "database-cluster",
  "level": "CRITICAL",
  "message": "Database connection pool fully exhausted. Deadlock detected.",
  "error_code": "CRIT_DB_POOL_EMPTY",
  "request_id": "req-9f2b84a1e70c"
}
```

### Severity Classification & Escalation Rules

| Level | Operational Meaning | Target Tables | Triggers Incident | Triggers SNS Alert |
| :--- | :--- | :--- | :---: | :---: |
| `INFO` | Routine operational telemetry | `cloudlog_events` | No | No |
| `WARNING` | Degraded conditions, cache latency | `cloudlog_events` | No | No |
| `ERROR` | Application exceptions, request failures | `cloudlog_events`, `cloudlog_incidents` | **Yes (Status: OPEN)** | No |
| `CRITICAL` | System outages, database exhaustion | `cloudlog_events`, `cloudlog_incidents` | **Yes (Status: OPEN)** | **Yes (Email/Push)** |

---

## Deployed AWS Infrastructure (`ap-south-1`)

The live infrastructure is provisioned and running in AWS Region `ap-south-1`:

| AWS Service | Resource Name / Endpoint | Purpose |
| :--- | :--- | :--- |
| **Amazon S3** | `cloudlog-raw-be259898` | Raw `.jsonl` log drop bucket with event notification |
| **AWS Lambda** | `cloudlog-processor-dev` | Ingests S3 logs, validates records, and indexes events |
| **AWS Lambda** | `cloudlog-api-dev` | REST controller backing API Gateway with RBAC checks |
| **DynamoDB** | `cloudlog_events` | PK: `service`, SK: `timestamp#event_id` |
| **DynamoDB** | `cloudlog_incidents` | PK: `incident_id`, GSI: `status-created_at-index` |
| **Amazon SNS** | `cloudlog-critical-alerts-dev` | High-priority push notifications for critical incidents |
| **Cognito Pool** | `ap-south-1_WD4fE4UTJ` | Identity provider with `Admin`, `Analyst`, `Viewer` roles |
| **Cognito Client**| `iufl9c8nnt2f3vd9jdif0bhh7` | Public SPA client with `USER_PASSWORD_AUTH` flow |
| **API Gateway** | `https://yldbrm495e.execute-api.ap-south-1.amazonaws.com` | HTTP API v2 with native Cognito JWT authorizer |

### Pre-Configured Demo User Accounts

| Role | Email | Password | Permissions |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@cloudlog.local` | `CloudLogAdmin#2026` | Full administrative access: view telemetry and resolve incidents |
| **Analyst** | `analyst@cloudlog.local` | `CloudLogAnalyst#2026` | Operational access: view telemetry and resolve incidents |
| **Viewer** | `viewer@cloudlog.local` | `CloudLogViewer#2026` | Read-only access: view telemetry (resolving incidents returns 403) |

---

## Getting Started

### 1. Local Development Setup

```bash
# Clone the repository
git clone https://github.com/FarazAkhtarKhan/CloudLog.git
cd CloudLog

# Initialize Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. Run Local Unit Test Suite (Offline)

Run all 68 unit tests executing against in-memory `moto` emulators:

```bash
pytest -v
```

### 3. Run Live AWS End-to-End Test Suite

Validate the live AWS infrastructure end-to-end:

```bash
AWS_PROFILE=terraform python scripts/test_e2e_aws.py
```

This automated script:
1. Generates and uploads a synthetic log batch to `s3://cloudlog-raw-be259898`.
2. Verifies the S3 trigger initiates `cloudlog-processor-dev` Lambda.
3. Asserts that all events appear in DynamoDB `cloudlog_events`.
4. Asserts that both ERROR and CRITICAL incidents appear in `cloudlog_incidents`.
5. Authenticates with AWS Cognito to retrieve JWT `IdToken`s.
6. Tests API Gateway `/statistics`, `/services`, and `/incidents` routes.
7. Confirms an Analyst can successfully resolve an incident (`200 OK`).
8. Confirms a Viewer attempting to resolve an incident receives `403 Forbidden`.

### 4. Ingest Sample Logs into AWS

Upload realistic multi-service logs to trigger live incidents:

```bash
AWS_PROFILE=terraform .venv/bin/python scripts/generate_sample_logs.py --count 25 --s3-bucket cloudlog-raw-be259898
```

### 5. Launch the Frontend Dashboard

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser. Use the **Quick Evaluation Logins** buttons on the login screen to sign in instantly as Admin, Analyst, or Viewer!

---

## Infrastructure Teardown

When your evaluation or demonstration is finished, destroy all AWS resources with a single command to ensure **zero residual charges**:

```bash
cd infrastructure/terraform
AWS_PROFILE=terraform terraform destroy -auto-approve
```
