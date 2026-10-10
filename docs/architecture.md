# CloudLog architecture

This document covers the data model, the API contract and the design decisions behind them.
For setup and the feature overview, see the [README](../README.md).

## 1. Service and deployment model

CloudLog is a **public-cloud, serverless** system. Every component is a managed service, so there are no
servers, operating systems or clusters to patch or size:

| Layer | Service | Model |
| --- | --- | --- |
| Compute | AWS Lambda (processor, API) | FaaS |
| Storage | Amazon S3 (raw logs, dashboard files) | Object storage, PaaS |
| Database | Amazon DynamoDB (3 tables) | NoSQL database, PaaS |
| Messaging | Amazon SNS (alerts), Amazon SQS (dead letters) | PaaS |
| Edge | API Gateway HTTP API, CloudFront, Cognito | PaaS |
| Operations | CloudWatch logs and alarms, Terraform | PaaS / IaC |

Two flows share the database but never call each other:

* **Ingestion** is *event-driven*: an S3 `ObjectCreated` event invokes the processor asynchronously.
* **Queries** are *request/response*: the dashboard calls API Gateway, which invokes the API Lambda.

## 2. Processing a log file

```
S3 ObjectCreated ─► processor Lambda
   1. get_object, stream lines              (memory stays flat for any file size)
   2. parse_line per line                   valid → LogEvent, invalid → Rejection(reason)
   3. EventsStore.save                      BatchWriteItem, TTL = now + 7 days
   4. detect(events)                        rules → Detection list
   5. IncidentsStore.apply(detection)       conditional UpdateItem / PutItem
   6. AlertPublisher.publish                for opened-critical, escalated or reopened-critical
   7. RunsStore.save                        counts, rejections, per-stage timings
```

On an exception the run is saved with `status = FAILED` and the error is re-raised, so Lambda's
async retry (2 attempts) and then the SQS dead-letter queue take over.

### Identifiers

| ID | Formula | Purpose |
| --- | --- | --- |
| `event_id` | `"evt_" + sha256(bucket:key:line)[:16]` | Retries rewrite the same item instead of duplicating it |
| `fingerprint` | `sha256(service + "|" + (error_code or message_shape))[:12]` | Lines describing the same problem group together |
| `incident_id` | `"inc_" + fingerprint` | One incident per problem; O(1) lookup |
| `run_id` | `"run_" + sha256(s3_uri)[:12]` | Links a run to its file; retries appear as separate attempts |

`message_shape` lower-cases the message and replaces numbers, UUIDs and long hex IDs with `#`, so
"timed out after 5012ms on 10.0.0.4" and "timed out after 5390ms on 10.0.0.9" share a fingerprint.
Brute-force incidents use `sha256("brute-force|" + ip)` so repeated attacks from one address group together.

### Applying a detection to an incident

```
UpdateItem  ADD occurrences :n, source_files :uri
            IF exists AND status IN (OPEN, ACKNOWLEDGED) AND NOT contains(source_files, :uri)
  ├─ succeeded → "updated"; escalate if ERROR and (occurrences ≥ 5 or a CRITICAL line arrived)
  └─ condition failed → GetItem
        ├─ source_files already has :uri → "duplicate" (a Lambda retry; do nothing)
        └─ missing or RESOLVED → PutItem IF not exists OR status = RESOLVED
              → "opened" or "reopened" (timeline kept); if the put loses a race, loop again
```

Escalation is itself conditional (`IF severity = ERROR`), so two concurrent Lambdas can't both alert.

## 3. Data model

### `cloudlog_events`

| Key | Attribute | Example |
| --- | --- | --- |
| PK | `service` | `payment-gateway` |
| SK | `sort_key` = `timestamp#event_id` | `2026-10-10T09:41:07.120Z#evt_8f14c2b9a70e31d4` |
| GSI `feed-index` PK | `feed_day` | `2026-10-10` |
| GSI `feed-index` SK | `sort_key` | |
| TTL | `expires_at` | epoch seconds, +7 days |

Other attributes: `event_id, timestamp, level, message (masked), fingerprint, source_s3_uri,
line_number, error_code?, endpoint?, ip_address? (subnet only), request_id?, pii_redacted?`.

Access patterns: one service's newest logs → Query the table by `service`; all services' newest logs →
Query `feed-index` for today, then yesterday; last 24 hours for analytics → Query `feed-index` with
`sort_key >= cutoff`. Timestamps are normalised to UTC `...sss Z`, so string order is time order.

### `cloudlog_incidents`

| Key | Attribute |
| --- | --- |
| PK | `incident_id` |
| GSI `status-updated_at-index` | `status`, `updated_at` |

Attributes: `fingerprint, log_fingerprint, status, severity, escalated, rule_id, category, service, title,
error_code?, source_ip?, occurrences, first_seen, last_seen, created_at, updated_at, acknowledged_at/by?,
resolved_at/by?, source_files (string set), sample_event_ids, timeline (list), alerts_sent, reopen_count`.
Point-in-time recovery is on.

### `cloudlog_pipeline_runs`

| Key | Attribute |
| --- | --- |
| PK | `stage` (always `processor`) |
| SK | `run_key` = `started_at#run_id` |
| TTL | `expires_at`, +3 days |

Attributes: `run_id, s3_uri, s3_key, trigger, scenario?, triggered_by?, size_bytes, status, error?,
total_lines, stored, rejected, rejections[], pii_redacted, levels{}, detections[], alerts[], stages{},
started_at, finished_at, duration_ms`.

## 4. API

All routes require a Cognito JWT, verified by API Gateway. Permissions are checked in the Lambda:

| Permission | Admin | Analyst | Viewer |
| --- | :-: | :-: | :-: |
| read | ✓ | ✓ | ✓ |
| triage (acknowledge, resolve) | ✓ | ✓ | |
| simulate | ✓ | ✓ | |
| reset demo data | ✓ | | |

| Method and route | Permission | Notes |
| --- | --- | --- |
| `GET /me` | read | Role and permissions of the caller |
| `GET /overview` | read | MapReduce over the last 24 h: totals, 60-minute timeline, service health, top error codes, MTTA/MTTR |
| `GET /events` | read | `level`, `service`, `q` (contains), `fingerprint`, `limit` ≤ 200 |
| `GET /incidents` | read | `status`, `limit` |
| `GET /incidents/{id}` | read | Incident plus its 25 newest log lines |
| `PATCH /incidents/{id}` | triage | `{"action": "acknowledge" \| "resolve", "note": "..."}`; 409 on an invalid transition |
| `GET /pipeline/runs` | read | Newest processor runs |
| `GET /rules` | read | Detection rule catalogue |
| `GET /simulator/scenarios` | read | Scenario catalogue |
| `POST /simulator/runs` | simulate | `{"scenario": id}` or `{"custom": {service, level, message, error_code?, repeat?}}`; uploads to S3 |
| `POST /admin/reset` | reset | Deletes every item in the three tables |

Errors are JSON `{"error": "..."}` with 400, 403, 404, 409 or 500.

## 5. Offline emulator

`python -m backend.local.emulator` starts moto's in-memory S3, DynamoDB and SNS, creates the same tables as
Terraform ([backend/local/resources.py](../backend/local/resources.py)), and then:

* an HTTP server converts each request into an API Gateway v2 event and calls `Api.handle`;
* a watcher thread lists the bucket every 0.4 s and calls `Processor.process_file` for each new
  `.jsonl` object, standing in for the S3 notification;
* Cognito is replaced by an `X-User-Role` header, honoured only when `CLOUDLOG_LOCAL_MODE=1`.

The unit tests use the same resource definitions, so tests, emulator and AWS share one schema.

## 6. Design decisions

**JSON Lines in S3 as the ingestion contract.** It is what log shippers (Fluent Bit, Vector, CloudWatch
exports) produce, it streams line by line, and S3 decouples producers from the processor: if Lambda is
throttled, files wait in the bucket instead of being dropped.

**Group by fingerprint instead of one incident per line.** The previous version opened an incident for
every ERROR line, so one outage produced dozens of tickets. Grouping, reopening and escalation follow the
model used by tools such as Sentry and PagerDuty.

**Count each file once (`source_files`).** Lambda's at-least-once delivery would otherwise inflate counters
on retries and could trigger false escalations.

**A per-day GSI for the global feed.** A Scan with `Limit` returns arbitrary items, not the newest ones.
Partitioning the feed by day gives a correctly ordered Query; at demo volumes one partition per day is far
below DynamoDB's per-partition limits.

**MapReduce for statistics.** The mapper is stateless and the reducer is associative, so the same functions
would scale out across workers; here they run inside one Lambda over at most 5,000 events.

**HTTP API and JWT authorizer.** Token checks happen at the gateway, so unauthenticated traffic never
reaches (or bills) Lambda; HTTP APIs are cheaper and faster than REST APIs.

**PII masked before storage.** Log messages are free text, which is where personal data leaks. Masking at
ingestion means nothing downstream (database, dashboard, alerts) ever holds it.

**An emulator rather than LocalStack.** It needs no Docker daemon, starts in about a second, and exercises
the real handler code; the trade-off is that IAM policies and the S3 trigger configuration are only tested
by `terraform validate` and the end-to-end script, not offline.
