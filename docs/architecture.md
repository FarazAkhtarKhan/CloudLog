# CloudLog Architecture & Design Specifications

This document outlines the architecture, data models, operational flows, and Architectural Decision Records (ADRs) for the **CloudLog** platform.

---

## 1. System Overview

CloudLog is an event-driven, serverless log analysis and incident detection platform built on AWS.

```text
[Application / Microservices]
             │
             ▼ (PutObject .jsonl)
     [Amazon S3 Bucket]
             │
             ▼ (s3:ObjectCreated:* Event Trigger)
     [AWS Lambda: Log Processor]
             │
             ├──► [Ingestion: S3 Object Fetch & Line Stream]
             ├──► [Analyzer: Validate, Classify & Hash Event ID]
             │
             ├──► [DynamoDB: cloudlog_events Table (All Valid Events)]
             │
             ├──► [DynamoDB: cloudlog_incidents Table (ERROR / CRITICAL)]
             │
             └──► [Amazon SNS Topic (CRITICAL Alerts Only)]

[Dashboard / Client] ──► [API Gateway] ──► [AWS Lambda: API Handler] ──► [DynamoDB Tables]
```

---

## 2. Event Ingestion Contract

### 2.1 S3 Delivery Format
* **Format:** JSON Lines (`.jsonl`)
* **Encoding:** UTF-8
* **Structure:** Exactly one self-contained JSON object per line.
* **Resilience:** Line-by-line processing ensures that a single corrupted or malformed line does not abort processing of the remaining valid records in the file.

### 2.2 Canonical JSON Schema (MVP)

#### Required Fields
| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `timestamp` | String | ISO 8601 UTC timestamp | `"2026-08-29T18:20:00.123Z"` |
| `service` | String | Originating service or subsystem identifier | `"payment-service"` |
| `level` | String | Operational severity classification | `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"` |
| `message` | String | Human-readable log narrative | `"Payment gateway timeout after 5000ms"` |

#### Valid MVP Severity Levels
1. `INFO` — Standard operational telemetry.
2. `WARNING` — Degraded conditions, latency spikes, or non-fatal anomalies.
3. `ERROR` — Application failures or unhandled exceptions (triggers incident creation).
4. `CRITICAL` — Fatal outages, database connectivity loss, or core system failures (triggers incident creation + real-time SNS notification).

*(Note: Specialized categories such as `SECURITY` or `PERFORMANCE` are deferred as optional future dimensions to preserve MVP simplicity).*

#### Optional Fields
| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `error_code` | String | Machine-readable error code for incident categorization | `"PGW_TIMEOUT_504"` |
| `endpoint` | String | HTTP route or internal RPC endpoint | `"/api/v1/checkout"` |
| `ip_address` | String | Client or source IP address | `"192.168.1.45"` |

---

## 3. Event ID & Idempotency Strategy

### 3.1 Event ID Generation Algorithm
To ensure deterministic identification and idempotent processing across AWS Lambda retries or file reprocessing, each record receives a generated `event_id`:

$$\text{event\_id} = \text{"evt\_"} + \text{SHA-256}(\text{bucket\_name} + \text{":"} + \text{object\_key} + \text{":"} + \text{line\_number})[0:16]$$

* **Implementation:** Standard library `hashlib.sha256(f"{bucket}:{key}:{line_number}".encode()).hexdigest()[:16]`.
* **Example:** `evt_8f14c2b9a70e31d4`

### 3.2 Idempotency & Collision Properties
* **Idempotent Writes:** In serverless architectures, AWS Lambda guarantees *at-least-once* execution. If a Lambda execution is retried following a transient failure, processing the same S3 object will generate identical `event_id` values. In DynamoDB, `PutItem` with identical primary keys will safely overwrite existing records rather than creating duplicate entries.
* **Collision Probability:** Truncating SHA-256 to 16 hexadecimal characters provides 64 bits of hash entropy ($2^{64} \approx 1.84 \times 10^{19}$ combinations). For our expected project scale, this provides a practically negligible collision probability across distinct record locations.

---

## 4. DynamoDB Data Models

### 4.1 Table 1: `cloudlog_events`
Stores all validated log records for historical inspection and service-level time-series queries.

* **Partition Key (PK):** `service` (String, e.g. `"payment-service"`)
* **Sort Key (SK):** `timestamp#event_id` (String, e.g. `"2026-08-29T18:20:00.123Z#evt_8f14c2b9a70e31d4"`)

#### Stored Attributes:
* `service` (String) — Primary partition key
* `timestamp#event_id` (String) — Primary sort key
* `timestamp` (String) — Raw ISO 8601 timestamp
* `event_id` (String) — Deterministic record identifier
* `level` (String) — `INFO`, `WARNING`, `ERROR`, `CRITICAL`
* `message` (String) — Log message
* `error_code` (String, optional) — Present only when provided
* `endpoint` (String, optional) — Present only when provided
* `ip_address` (String, optional) — Present only when provided
* `source_s3_uri` (String) — Originating S3 URI (e.g. `"s3://cloudlog-raw/2026/08/29/logs.jsonl"`)
* `processed_at` (String) — ISO 8601 ingestion timestamp

> **Note on Query Expressions:** Because the sort key is composed of `timestamp#event_id`, DynamoDB `BETWEEN` or range queries cannot use bare timestamp strings as exact boundary values. The exact query expressions and sort key boundary patterns will be designed during repository and API layer implementation.

### 4.2 Table 2: `cloudlog_incidents`
Stores actionable operational anomalies and incident lifecycles.

### 4.2 Table 2: `cloudlog_incidents`
Stores actionable operational anomalies and incident lifecycles.

* **Partition Key (PK):** `incident_id` (String, e.g. `"inc_8f14c2b9a70e31d4"`)
* **Global Secondary Index (GSI):** `status-created_at-index`
  * **GSI Partition Key:** `status` (String, e.g. `"OPEN"`, `"RESOLVED"`)
  * **GSI Sort Key:** `created_at` (String, ISO 8601 UTC timestamp)

#### Stored Attributes:
* `incident_id` (String) — Primary partition key (`"inc_" + event_id[4:]`)
* `service` (String) — Originating service name
* `severity` (String) — `ERROR` or `CRITICAL`
* `status` (String) — `OPEN` or `RESOLVED` (starts as `OPEN`)
* `message` (String) — Root cause error message
* `error_code` (String, optional) — Machine error code when present
* `source_event_id` (String) — Logical reference to triggering event in `cloudlog_events`
* `source_s3_uri` (String) — S3 file origin
* `created_at` (String) — ISO 8601 timestamp of incident creation
* `resolved_at` (String, optional) — ISO 8601 timestamp when resolved

#### Incident Creation & Escalation Rules:
* `INFO` $\rightarrow$ Event only (No incident)
* `WARNING` $\rightarrow$ Event only (No incident)
* `ERROR` $\rightarrow$ Event + Incident (status: `OPEN`, severity: `ERROR`, no SNS alert)
* `CRITICAL` $\rightarrow$ Event + Incident (status: `OPEN`, severity: `CRITICAL`, triggers SNS alert)

#### Idempotency & Deterministic Incident ID:
* `incident_id` is derived deterministically from the triggering log event's `event_id`:
  $$\text{incident\_id} = \text{"inc\_"} + \text{event.event\_id}[4:]$$
  *(e.g., `evt_8f14c2b9a70e31d4` $\rightarrow$ `inc_8f14c2b9a70e31d4`)*
* Processing the same event again produces identical keys and performs an idempotent write, preventing duplicate incidents.

#### Lifecycle:
$$\text{OPEN} \xrightarrow{\text{resolve\_incident()}} \text{RESOLVED}$$
*(Intermediate states such as `IN_PROGRESS` or `TRIAGED` are intentionally excluded to keep the MVP simple).*

---

## 5. Architectural Decision Records (ADRs)

### ADR 001: Log Ingestion Format & S3 Delivery
* **Status:** `ACCEPTED`
* **Decision:** Ingest logs using **JSON Lines (`.jsonl`)** delivered to S3.
* **Rationale:** Industry standard for structured log aggregation (AWS CloudWatch, FluentBit, Vector). Enables robust line-by-line streaming without buffering entire multi-megabyte JSON arrays in memory.

### ADR 002: Dual-Table DynamoDB Schema & GSI Incident Querying
* **Status:** `ACCEPTED`
* **Decision:** Separate `cloudlog_events` (`PK = service`, `SK = timestamp#event_id`) and `cloudlog_incidents` (`PK = incident_id`, GSI: `status-created_at-index`).
* **Rationale:** Direct O(1) incident lookups and updates by `incident_id`, while the GSI enables high-performance chronological queries for active (`OPEN`) incidents on the dashboard without table scans.

### ADR 003: Deterministic Event IDs for Serverless Idempotency
* **Status:** `ACCEPTED`
* **Decision:** Generate `event_id = "evt_" + SHA-256(bucket:key:line_number)[:16]`.
* **Rationale:** Guarantees idempotency during Lambda retries without requiring client-side coordination. Offers negligible collision probability for the project scale.

### ADR 004: Local Development & Emulation via Pytest + Moto
* **Status:** `ACCEPTED`
* **Decision:** Standardize on in-memory `pytest` and `moto` for local testing.
* **Rationale:** Fast execution, zero Docker container overhead, seamless execution in local environments and CI pipelines.

### ADR 005: AWS Cognito JWT Authorizer & Stateless RBAC
* **Status:** `ACCEPTED`
* **Decision:** Implement stateless authentication using Amazon Cognito User Pools with native API Gateway HTTP API JWT Authorizers.
* **Rationale:** Offloads token verification, cryptographic signature checks, and expiration validation to AWS edge infrastructure before requests ever reach Lambda. Eliminates custom auth microservice maintenance and ensures zero runtime token database lookups.

### ADR 006: Direct Browser Cognito Authentication (`USER_PASSWORD_AUTH`)
* **Status:** `ACCEPTED`
* **Decision:** Perform direct authentication from the client browser against the public Cognito Identity Provider endpoint using standard `fetch`.
* **Rationale:** Eliminates backend compute costs and proxy hops for user login while keeping credentials completely out of API Gateway logs.

### ADR 007: API Gateway HTTP API v2 over REST API v1
* **Status:** `ACCEPTED`
* **Decision:** Deploy API Gateway HTTP API (`v2`) instead of traditional REST API (`v1`).
* **Rationale:** HTTP APIs offer ~70% lower latency, native JWT authorizer integration, automatic CORS handling, and ~71% lower cost ($1.00/million requests vs $3.50/million requests), perfectly tailored for modern Single Page Applications (SPAs).

---

## 6. API Gateway HTTP API v2 & Controller Contract

The CloudLog API exposes RESTful endpoints backed by a single Lambda controller (`cloudlog-api-dev`):

| Method | Route | Auth Required | Allowed Roles | Description |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/statistics` | Yes | Admin, Analyst, Viewer | System-wide ingestion and incident totals |
| `GET` | `/services` | Yes | Admin, Analyst, Viewer | Unique list of monitored services |
| `GET` | `/events` | Yes | Admin, Analyst, Viewer | Paginated telemetry logs with level/service filters |
| `GET` | `/events/critical`| Yes | Admin, Analyst, Viewer | Filtered list of critical incidents |
| `GET` | `/incidents` | Yes | Admin, Analyst, Viewer | Operational incidents with `status` filter |
| `GET` | `/incidents/{id}` | Yes | Admin, Analyst, Viewer | Detailed inspection of a specific incident |
| `PATCH` | `/incidents/{id}` | Yes | **Admin, Analyst only** | Lifecycle transition from `OPEN` to `RESOLVED` |

---

## 7. Role-Based Access Control (RBAC) Specification

Access control is enforced at two distinct security perimeters:
1. **API Gateway Perimeter (Authentication):** API Gateway validates the signature and issuer of the incoming Cognito JWT `IdToken`. Invalid, expired, or tampered tokens receive `401 Unauthorized` before invoking the backend.
2. **Lambda Application Perimeter (Authorization):** The API Lambda inspects `cognito:groups` claims:
   - **`Admin`**: Full operational access. Can view telemetry, list incidents, and resolve active incidents.
   - **`Analyst`**: Incident response access. Can view telemetry, list incidents, and mark incidents as resolved.
   - **`Viewer`**: Read-only stakeholder access. Can monitor telemetry and review incident queues. Attempting `PATCH /incidents/{id}` strictly returns `403 Forbidden`.

---

## 8. Frontend Single-Page Application (SPA)

* **Framework:** React 19 + Vite
* **Styling:** Custom Vanilla CSS with dark-mode glassmorphic aesthetics, responsive grid layouts, and color-coded severity badges.
* **Session Management:** Secure browser `sessionStorage` containing Cognito JWT `IdToken`.
* **Real-Time Experience:** 10-second polling interval with manual refresh option and live animated state badges.

---

## 9. Infrastructure as Code (Terraform) Profile

* **Location:** `infrastructure/terraform/`
* **Structure:** Flat architecture (`main.tf`, `s3.tf`, `dynamodb.tf`, `lambda.tf`, `api_lambda.tf`, `api_gateway.tf`, `cognito.tf`, `sns.tf`, `cloudwatch.tf`, `iam.tf`, `outputs.tf`).
* **Cost Profile:** 100% Free Tier compliant on AWS (`ap-south-1`):
  - DynamoDB: On-demand (pay-per-request) or provisioned within 25 RCU/WCU free tier.
  - S3: Standard storage with limited retention.
  - Lambda: Invocations within 1 million free requests/month.
  - Cognito: Up to 50,000 Monthly Active Users (MAU) free.
  - CloudWatch: 7-day log retention to prevent accumulation of storage fees.

---

## 10. Operational Procedures

### 10.1 Running Local Tests
```bash
source .venv/bin/activate
pytest -v
```

### 10.2 End-to-End AWS Validation
```bash
AWS_PROFILE=terraform python scripts/test_e2e_aws.py
```

### 10.3 Generating and Ingesting Live Telemetry
```bash
# Generate and upload a 20-record batch directly to live S3
AWS_PROFILE=terraform .venv/bin/python scripts/generate_sample_logs.py --count 20 --s3-bucket cloudlog-raw-be259898
```

### 10.4 Starting Local Frontend Dashboard
```bash
cd frontend
npm run dev
```

### 10.5 Infrastructure Teardown
When the demonstration or evaluation is complete, destroy all cloud resources with zero residual billing:
```bash
cd infrastructure/terraform
AWS_PROFILE=terraform terraform destroy -auto-approve
```

