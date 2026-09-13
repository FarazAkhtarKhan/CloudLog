# CloudLog
> **Serverless Critical Log Analysis and Incident Detection System**

CloudLog is a serverless application designed to collect, analyze, and monitor application logs across microservices in real time. Instead of running expensive, always-on server clusters (like Elasticsearch or Datadog) that cost money even when idle, CloudLog uses pay-per-use AWS serverless services (Amazon S3, AWS Lambda, DynamoDB, API Gateway, and Amazon SNS). 

When applications send logs, CloudLog automatically detects critical system errors, files an incident ticket, alerts administrators immediately via email, and displays everything on a web dashboard.

---

## The Problem CloudLog Solves

When deploying modern cloud applications and microservices:
1. **High Costs**: Popular log monitoring tools (like Datadog, Splunk, or self-hosted Elasticsearch clusters) require running servers 24/7. This often costs $50–$300+ every month just to keep the servers running, even during low-traffic periods.
2. **Delayed Incident Detection**: When a critical failure occurs (such as a database crashing or a payment gateway timing out), teams often discover the problem only after customers complain.
3. **Complex Maintenance**: Managing logging servers requires ongoing patching, scaling, storage re-indexing, and cluster backups.

### The CloudLog Solution
* **Zero Cost When Idle**: Built 100% on the **AWS Free Tier**. When no logs are arriving, compute cost is **$0**.
* **Instant Outage Alerts**: Critical errors trigger immediate push notifications to administrators through **Amazon SNS**.
* **Automated Incident Tracking**: Errors are automatically organized into an incident queue with lifecycle tracking (`OPEN` → `RESOLVED`).
* **Interactive Web Dashboard**: A responsive web interface allows engineers to inspect logs, view statistics, and test incident scenarios with a single click.

---

## How It Works (Step-by-Step Architecture)

The system is split into two clean workflows:

### 1. The Log Ingestion & Incident Detection Pipeline
```
[Microservices / Applications]
              │
              ▼ 1. Uploads .jsonl log files
      [Amazon S3 Bucket]
              │
              ▼ 2. S3 triggers function automatically on file drop
     [AWS Lambda: Log Processor]
              │
              ├──► 3. Parses and saves all logs into [DynamoDB: cloudlog_events]
              │
              ├──► 4. If ERROR or CRITICAL, creates incident in [DynamoDB: cloudlog_incidents]
              │
              └──► 5. If CRITICAL, sends instant email alert via [Amazon SNS]
```

1. **Log Upload**: Microservices drop structured `.jsonl` log files into an **Amazon S3** bucket.
2. **Automatic Trigger**: S3 automatically notifies **AWS Lambda** the instant a file arrives.
3. **Parsing & Validation**: Lambda streams the file line-by-line, validates the JSON format, and generates a unique fingerprint for each log to prevent duplicate entries.
4. **Database Storage**: All valid logs are saved in **Amazon DynamoDB** (`cloudlog_events`).
5. **Incident Escalation**: 
   * `INFO` and `WARNING` logs are stored for reference.
   * `ERROR` logs automatically create an `OPEN` incident in `cloudlog_incidents`.
   * `CRITICAL` logs (like database crashes or transaction outages) create an incident **and** send an immediate push email notification via **Amazon SNS**.

### 2. The Dashboard & Query Pipeline
```
[React 19 Web Dashboard]
              │
              ▼ 1. User signs in via email/password
      [AWS Cognito User Pool] (Issues verified JWT tokens)
              │
              ▼ 2. Browser calls API with Bearer token
    [Amazon API Gateway HTTP API]
              │
              ▼ 3. Verifies token and routes to Lambda
     [AWS Lambda: API Handler]
              │
              ▼ 4. Reads telemetry / Updates incident status
    [Amazon DynamoDB Tables]
```

1. **Authentication**: Users sign into the dashboard using **AWS Cognito**.
2. **Role Verification**: API Gateway validates the user's security token and passes role permissions (`Admin`, `Analyst`, or `Viewer`).
3. **Data Retrieval**: The API Lambda fetches real-time counters, incident lists, and telemetry streams from DynamoDB.
4. **Incident Resolution**: Analysts and Admins can click "Resolve" to close active incidents.

---

## Key Features

* **Real-Time Web Dashboard**: Built with React 19 and custom dark-mode styling. Includes auto-refreshing metrics, log filtering by service/severity, and an incident response table.
* **In-Browser Incident Simulator**: Built-in simulator with 1-click presets (Database Deadlock, Payment 504, Auth Bursts). You can trigger real cloud incidents live from the browser without running any terminal commands!
* **Role-Based Access Control (RBAC)**:
  * **Admin**: Full access to view logs and resolve incidents.
  * **Analyst**: Operational access to monitor systems and resolve incidents.
  * **Viewer**: Read-only access for stakeholders (attempting to modify incidents is safely blocked).
* **Duplicate Prevention (Idempotent Processing)**: Uses deterministic SHA-256 hashing based on the S3 file and line number. Even if AWS Lambda retries processing the same file, no duplicate records or duplicate incidents are created.
* **100% Infrastructure as Code (Terraform)**: The entire AWS setup (S3, Lambda, DynamoDB, API Gateway, Cognito, SNS, CloudWatch) is defined in clean Terraform files and can be deployed or deleted with a single command.
* **Comprehensive Test Coverage**: **70 passing automated tests** verifying log parsing, DynamoDB persistence, incident creation rules, SNS alert dispatching, and API security.

---

## Log Format Contract

Applications deliver logs as JSON Lines (`.jsonl`). Each line is a self-contained JSON object:

```json
{
  "timestamp": "2026-09-05T18:20:00.123Z",
  "service": "database-cluster",
  "level": "CRITICAL",
  "message": "Database connection pool exhausted. Deadlock detected.",
  "error_code": "CRIT_DB_DEADLOCK",
  "request_id": "req-9f2b84a1e70c"
}
```

### Log Levels & System Behavior

| Level | What It Represents | Stored in Events? | Creates Incident? | Sends SNS Alert? |
| :--- | :--- | :---: | :---: | :---: |
| `INFO` | Routine operations (e.g. user logged in, order created) | Yes | No | No |
| `WARNING` | Degraded performance, minor latency, high cache usage | Yes | No | No |
| `ERROR` | Unhandled exceptions, failed requests, service timeouts | Yes | **Yes (Status: OPEN)** | No |
| `CRITICAL` | Service down, database deadlock, payment gateway failure | Yes | **Yes (Status: OPEN)** | **Yes (Email Alert)** |

---

## Active AWS Deployment Details

The system is deployed and active in AWS Region **`ap-south-1` (Mumbai)**:

| Component | Resource Name / Endpoint |
| :--- | :--- |
| **S3 Ingestion Bucket** | `cloudlog-raw-c112484d` |
| **Lambda Processor** | `cloudlog-processor-dev` |
| **Lambda API Handler** | `cloudlog-api-dev` |
| **DynamoDB Events Table** | `cloudlog_events` |
| **DynamoDB Incidents Table** | `cloudlog_incidents` |
| **Amazon SNS Topic** | `arn:aws:sns:ap-south-1:794038220540:cloudlog-critical-alerts-dev` |
| **Cognito User Pool ID** | `ap-south-1_BqIJiqapr` |
| **Cognito Client ID** | `o46k2sr3chiu311q6g199lmit` |
| **API Gateway URL** | `https://n6ccjux86f.execute-api.ap-south-1.amazonaws.com` |

---

## Quickstart & Evaluation Guide

### 1. Start the Frontend Dashboard
To run the web interface locally:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your web browser.

### 2. Sign In (Pre-Configured Demo Accounts)
The login screen has **one-click login buttons** for instant evaluation:

* **Analyst**: `analyst@cloudlog.local` / `CloudLogAnalyst#2026` *(Recommended for testing)*
* **Admin**: `admin@cloudlog.local` / `CloudLogAdmin#2026`
* **Viewer**: `viewer@cloudlog.local` / `CloudLogViewer#2026` *(Read-only)*

### 3. How to Trigger and Test an Incident Live

You can trigger a live incident in two different ways:

#### Option A: From the Web Dashboard (Easiest)
1. Click the red **⚡ Trigger Incident** button in the dashboard header.
2. Click the **"DB Deadlock"** preset (or choose another scenario).
3. Click **"Trigger in AWS Live"**.
4. The dashboard uploads the log to S3, Lambda analyzes it, and the new incident appears in the **Incident Response Queue** in 1–2 seconds!

#### Option B: From the Terminal
Run the provided helper script:
```bash
./trigger_incident.sh
```
Or send a full batch of 25 multi-service logs:
```bash
./send_logs.sh
```

### 4. How to Receive Real-Time Email Alerts from SNS
To receive email notifications on your personal email whenever a `CRITICAL` incident occurs:

```bash
AWS_PROFILE=terraform aws sns subscribe \
  --topic-arn arn:aws:sns:ap-south-1:794038220540:cloudlog-critical-alerts-dev \
  --protocol email \
  --notification-endpoint your-email@gmail.com \
  --region ap-south-1
```
Open your email inbox and click **"Confirm subscription"**. Then trigger any `CRITICAL` incident to receive the alert.

---

## Testing & Quality Assurance

### Run Local Unit Tests (Offline)
Run all 70 unit tests using `pytest`:

```bash
.venv/bin/pytest -v
```
All 70 tests pass in ~4 seconds without needing internet access or active AWS credentials.

### Run Automated End-to-End AWS Integration Test
Verify the real AWS cloud infrastructure end-to-end:

```bash
AWS_PROFILE=terraform .venv/bin/python scripts/test_e2e_aws.py
```
This script uploads real logs to S3, asserts that DynamoDB recorded the events, tests API Gateway endpoints, and validates RBAC permissions.

---

## How to Stop Billing (Destroy Infrastructure)

When you are done evaluating or presenting the project, you can destroy all AWS resources with a single command to ensure **$0 future charges**:

```bash
cd infrastructure/terraform
AWS_PROFILE=terraform terraform destroy -auto-approve
```

All S3 buckets, DynamoDB tables, Lambdas, and Cognito pools will be cleanly removed.

