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

* **Partition Key (PK):** `incident_id` (String, e.g. `"INC-20260829-8F14C2B9"`)
* **Sort Key (SK):** `created_at` (String, ISO 8601)

#### Stored Attributes:
* `incident_id` (String)
* `created_at` (String)
* `service` (String)
* `severity` (String) — `ERROR` or `CRITICAL`
* `status` (String) — `OPEN`, `RESOLVED`
* `error_code` (String, optional)
* `message` (String)
* `source_event_id` (String) — Pointer to originating log record in `cloudlog_events`
* `source_s3_uri` (String)
* `resolved_at` (String, optional)

---

## 5. Architectural Decision Records (ADRs)

### ADR 001: Log Ingestion Format & S3 Delivery
* **Status:** `ACCEPTED`
* **Decision:** Ingest logs using **JSON Lines (`.jsonl`)** delivered to S3.
* **Rationale:** Industry standard for structured log aggregation (AWS CloudWatch, FluentBit, Vector). Enables robust line-by-line streaming without buffering entire multi-megabyte JSON arrays in memory.

### ADR 002: Dual-Table DynamoDB Schema & Collision-Safe Sort Keys
* **Status:** `ACCEPTED`
* **Decision:** Separate `cloudlog_events` (`PK = service`, `SK = timestamp#event_id`) and `cloudlog_incidents` (`PK = incident_id`, `SK = created_at`).
* **Rationale:** Appending `event_id` to the sort key prevents record overwrites when multiple events share identical timestamps while retaining single-service time-series organization.

### ADR 003: Deterministic Event IDs for Serverless Idempotency
* **Status:** `ACCEPTED`
* **Decision:** Generate `event_id = "evt_" + SHA-256(bucket:key:line_number)[:16]`.
* **Rationale:** Guarantees idempotency during Lambda retries without requiring client-side coordination. Offers negligible collision probability for the project scale.

### ADR 004: Local Development & Emulation via Pytest + Moto
* **Status:** `ACCEPTED`
* **Decision:** Standardize on in-memory `pytest` and `moto` for local testing.
* **Rationale:** Fast execution, zero Docker container overhead, seamless execution in local environments and CI pipelines.
