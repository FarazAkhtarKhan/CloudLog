# CloudLog Architecture & Design Specifications

This document outlines the architecture, data models, operational flows, and Architectural Decision Records (ADRs) for the CloudLog platform.

---

## 1. System Overview

CloudLog is designed as a serverless event-driven pipeline that handles ingestion, parsing, indexing, and incident escalation for distributed application logs on AWS.

```text
[Application / Microservices]
         │
         │ (1) PutObject (.json / .jsonl)
         ▼
 ┌───────────────┐
 │   Amazon S3   │
 └───────┬───────┘
         │ (2) s3:ObjectCreated:* Event
         ▼
 ┌───────────────┐
 │  AWS Lambda   │◄── Ingestion & Extraction (backend/ingestion)
 │ Log Processor │──► Validation & Parsing    (backend/analyzer)
 └───────┬───────┘──► Incident Creation       (backend/incidents)
         │
         ├───────────────────────────────┬───────────────────────────────┐
         │ (3a) All Events               │ (3b) Errors / Critical        │ (3c) Critical / Security Only
         ▼                               ▼                               ▼
 ┌───────────────┐               ┌───────────────┐               ┌───────────────┐
 │   DynamoDB    │               │   DynamoDB    │               │  Amazon SNS   │
 │cloudlog_events│               │  cloudlog_    │               │Critical Alerts│
 └───────┬───────┘               │   incidents   │               └───────────────┘
         │                       └───────┬───────┘
         │                               │
         └───────────────┬───────────────┘
                         │
                         ▼ (4) Query API
                 ┌───────────────┐
                 │  API Gateway  │
                 │       +       │
                 │  AWS Lambda   │
                 └───────────────┘
```

---

## 2. Pipeline Components

### 2.1 Ingestion Layer (`backend/ingestion`)
- **Trigger**: S3 bucket notification invokes the Log Processor Lambda upon new file arrival (`s3:ObjectCreated:*`).
- **File Handling**: Supports both individual JSON objects and line-delimited JSON (`.jsonl`).
- **Payload Extraction**: Downloads the file stream from S3, splits line records, and passes them to the analyzer.

### 2.2 Analysis & Classification (`backend/analyzer`)
- **Schema Validation**: Validates that incoming records contain required fields (`timestamp`, `service_name`, `log_level`, `message`).
- **Sanitization**: Normalizes timestamps to ISO 8601 UTC and trims noisy payloads.
- **Classification**: Determines severity levels (`INFO`, `WARNING`, `ERROR`, `CRITICAL`, `SECURITY`) and classifies error codes.

### 2.3 Incident Management & Escalation (`backend/incidents`)
- **Incident Deduplication & Creation**: Any log with severity `ERROR`, `CRITICAL`, or `SECURITY` generates a dedicated incident record with status `OPEN`.
- **Notification Dispatch**: Logs classified as `CRITICAL` or `SECURITY` immediately publish structured alert payloads to the configured Amazon SNS topic.

### 2.4 Query API (`backend/api`)
- Provides REST endpoints via API Gateway and Lambda for querying logs by service/time range and viewing active incidents.

---

## 3. Data Storage & Schema Design

DynamoDB is used for persistence with a dual-table strategy to isolate high-throughput append-only logs from stateful incident tracking.

### Table 1: `cloudlog_events`
Stores all validated log records for historical querying and auditing.

| Attribute | Type | Key Type | Description |
| :--- | :--- | :--- | :--- |
| `service_name` | String | **Partition Key (PK)** | Identifies the originating service (e.g. `payment-service`) |
| `timestamp` | String | **Sort Key (SK)** | ISO 8601 timestamp (e.g. `2026-08-25T14:31:05.412Z`) |
| `event_id` | String | Attribute | Unique UUID for the log entry |
| `log_level` | String | Attribute | `INFO`, `WARNING`, `ERROR`, `CRITICAL`, `SECURITY` |
| `message` | String | Attribute | Human-readable log message |
| `error_code` | String | Attribute | Optional error identifier (e.g. `PGW_TIMEOUT_504`) |
| `ip_address` | String | Attribute | Origin IP address |
| `endpoint` | String | Attribute | HTTP route or internal RPC endpoint |
| `metadata` | Map | Attribute | Arbitrary context (user IDs, request IDs, latencies) |
| `ttl` | Number | TTL Attribute | Unix timestamp for automatic item expiration (e.g. 30 days) |

### Table 2: `cloudlog_incidents`
Stores actionable operational anomalies and security events.

| Attribute | Type | Key Type | Description |
| :--- | :--- | :--- | :--- |
| `incident_id` | String | **Partition Key (PK)** | Unique incident identifier (e.g. `INC-20260825-4F8A`) |
| `created_at` | String | **Sort Key (SK)** | ISO 8601 creation timestamp |
| `service_name` | String | Attribute | Originating service |
| `severity` | String | Attribute | `ERROR`, `CRITICAL`, or `SECURITY` |
| `status` | String | Attribute | `OPEN`, `INVESTIGATING`, `RESOLVED` |
| `error_code` | String | Attribute | Associated error code |
| `message` | String | Attribute | Root cause error message |
| `source_event_id`| String | Attribute | Pointer to the corresponding record in `cloudlog_events` |
| `resolved_at` | String | Attribute | ISO 8601 resolution timestamp |

---

## 4. Architectural Decision Records (ADRs)

### ADR-001: Event-Driven S3 Ingestion vs. Continuous Streaming
* **Status**: Accepted
* **Context**: We evaluated whether to ingest logs via streaming (Amazon Kinesis Data Streams / Apache Kafka) or file uploads to Amazon S3 with event notifications.
* **Decision**: Use S3 bucket notifications triggering AWS Lambda.
* **Rationale**:
  * For batch log uploads and services writing buffered log chunks, S3 event notifications provide a zero-maintenance, zero-idle-cost ingestion path.
  * Avoids paying hourly shard costs for Kinesis streams during low-traffic periods.
  * The S3 bucket automatically serves as a durable, raw log archive.

### ADR-002: Dual-Table DynamoDB Modeling vs. Single-Table Design
* **Status**: Accepted
* **Context**: We evaluated using a single overloaded DynamoDB table with composite keys (`PK`, `SK`, `GSI1PK`, `GSI1SK`) versus two distinct tables (`cloudlog_events` and `cloudlog_incidents`).
* **Decision**: Adopt a two-table design.
* **Rationale**:
  * `cloudlog_events` is a high-volume, append-only time-series dataset that benefits from a short Time-To-Live (TTL) expiration policy.
  * `cloudlog_incidents` is a low-volume, mutable dataset that requires updates to lifecycle status (`OPEN` → `RESOLVED`) and longer-term retention.
  * Separating them prevents high log volumes from impacting incident queries and allows independent capacity and TTL configuration.

### ADR-003: Structured JSON as the Canonical Format
* **Status**: Accepted
* **Context**: Applications produce logs in multiple formats (raw plaintext, standard Syslog, Apache combined format, JSON).
* **Decision**: Require structured JSON (single object or newline-delimited JSON `.jsonl`) as the initial ingestion contract.
* **Rationale**:
  * Eliminates complex, fragile regular expression parsing in the core Lambda path.
  * Enforces predictable schemas with typed metadata (e.g. integer latencies, structured user context).
  * Custom format adaptors can be added later as pre-processors without altering the core analyzer engine.

### ADR-004: In-Memory Offline Testing with Moto
* **Status**: Accepted
* **Context**: Testing serverless AWS architectures often requires either deploying to real AWS test accounts or running heavy containerized emulators (like LocalStack).
* **Decision**: Use Python `pytest` alongside `moto` for local testing.
* **Rationale**:
  * Complete test suite runs in under 2 seconds without network access or cloud credentials.
  * Integrates seamlessly into CI pipelines without container startup delays.
  * Mock coverage for S3, DynamoDB, and SNS in `moto` matches AWS API behavior accurately for our use cases.

---

## 5. Reliability & Error Handling

1. **Malformed Payloads**: If a file in S3 contains corrupted or unparseable JSON lines, the parser logs a warning, skips the invalid line, and continues processing the remainder of the file.
2. **Idempotency**: Event IDs are generated deterministically based on `service_name + timestamp + message hash` or UUIDs to prevent duplicate record insertion during S3 event retries.
3. **Dead Letter Queues (DLQ)**: In production deployment, unhandled Lambda execution failures will route to an Amazon SQS DLQ for inspection and reprocessing.
