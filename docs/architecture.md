# CloudLog Architecture & Design Decisions

This document records the architectural design, system models, and Architectural Decision Records (ADRs) for the **CloudLog** platform.

---

## 1. System Overview

CloudLog is an event-driven, cloud-native log analysis and incident detection platform built on AWS serverless technologies.

```text
[Application / Server / Generator]
                │
                ▼ (Structured JSON Logs)
       [Amazon S3 Bucket]
                │
                ▼ (ObjectCreated Event Trigger)
       [AWS Lambda: Log Processor]
                │
                ├──► [Python Analyzer: Parse, Validate, Classify]
                │
                ├──► [Amazon DynamoDB: cloudlog_events Table]
                │
                ├──► [Amazon DynamoDB: cloudlog_incidents Table (if Warning/Error/Critical)]
                │
                └──► [Amazon SNS Topic: Critical Incident Alerts (if Severity == CRITICAL)]

[Dashboard / Client] ──► [API Gateway] ──► [AWS Lambda: API Handler] ──► [DynamoDB Tables]
```

---

## 2. Architectural Decision Records (ADRs)

### ADR 001: Log Ingestion Format
* **Date:** Phase 1 Design
* **Status:** `ACCEPTED`
* **Decision:** Accept **Structured JSON logs only** for the MVP.
* **Context & Rationale:**
  * Modern cloud-native and containerized workloads primarily emit structured JSON logs.
  * Ensures deterministic parsing and strict schema validation.
  * Minimizes brittle regular expression edge cases and reduces unnecessary parsing overhead.
  * Significantly reduces development time, fitting the 3–5 week course timeline.
* **Deferred Feature:** Multi-format/Regex fallback parser (Apache, Syslog, raw text) is documented as a future stretch goal if time permits after the core system is verified.

---

### ADR 002: Persistence Strategy & Database Design
* **Date:** Phase 1 Design
* **Status:** `ACCEPTED`
* **Decision:** Adopt a **Two-Table DynamoDB Design** (`cloudlog_events` and `cloudlog_incidents`).
* **Context & Rationale:**
  * High-frequency telemetry (raw/parsed log events) and actionable low-frequency operational entities (incidents) have distinct lifecycle and query patterns.
  * **Table 1: `cloudlog_events`**
    * *Partition Key (PK):* `service_name` (String)
    * *Sort Key (SK):* `timestamp` (String / ISO 8601)
    * *Purpose:* Time-series log querying per microservice / subsystem.
  * **Table 2: `cloudlog_incidents`**
    * *Partition Key (PK):* `incident_id` (String - e.g. `INC-20260825-001`)
    * *Sort Key (SK):* `created_at` (String / ISO 8601)
    * *GSI 1 (Optional for API):* `status` (PK) + `created_at` (SK) for listing `OPEN`/`RESOLVED` incidents.
    * *Purpose:* Managing actionable incident lifecycles, states, and escalations.
  * **Why not Single-Table Design for MVP:** Single-table designs add cognitive overhead and indexing complexity that is difficult to justify and explain within a 3–5 week student semester project. Two tables are clean, maintainable, and viva-friendly.

---

### ADR 003: Local Development & Emulation Strategy
* **Date:** Phase 1 Design
* **Status:** `ACCEPTED`
* **Decision:** Utilize **`pytest` + `moto`** with local JSON event fixtures for automated local development and testing.
* **Context & Rationale:**
  * `moto` provides fast, in-memory AWS service mocking without requiring Docker containers or heavy background daemons.
  * Unit and integration tests can run entirely offline in milliseconds and seamlessly in GitHub Actions CI.
  * Eliminates configuration debugging time associated with local emulation containers.
* **Deferred Feature:** LocalStack integration is retained as an optional local simulation bonus after the core pipeline and tests are stable.

---

## 3. Standard JSON Log Schema (MVP Contract)

Every log file uploaded to S3 contains JSON records (single object or newline-delimited JSON `.jsonl`) conforming to the following structure:

```json
{
  "timestamp": "2026-08-25T14:30:00.123Z",
  "service_name": "payment-service",
  "log_level": "ERROR",
  "message": "Payment gateway timeout after 5000ms",
  "error_code": "PGW_TIMEOUT_504",
  "ip_address": "192.168.1.45",
  "endpoint": "/api/v1/checkout",
  "metadata": {
    "user_id": "usr_99812",
    "retry_count": 3
  }
}
```

### Supported Severity Levels:
1. `INFO` — Informational operational messages (stored in `cloudlog_events`).
2. `WARNING` — Potential anomalies or degraded performance (stored in `cloudlog_events`, optionally flagged).
3. `ERROR` — Application faults/exceptions (stored in `cloudlog_events`, triggers incident in `cloudlog_incidents`).
4. `CRITICAL` — Severe outages, database connection drops, fatal service crashes (stored in `cloudlog_events`, creates `cloudlog_incidents`, triggers **SNS alert**).
5. `SECURITY` — Authentication failures, unauthorized access attempts (classified and tracked as security incidents).
