# CloudLog — Automated Cloud Log Analysis & Incident Detection Platform

An event-driven, cloud-native log ingestion, analysis, and automated incident response system built for AWS serverless architecture.

---

## 📌 Project Overview

CloudLog automates the detection, classification, and alerting of operational and security incidents across distributed cloud environments. When services write structured logs to Amazon S3, an automated serverless pipeline immediately parses the records, indexes them in Amazon DynamoDB, flags operational incidents, and dispatches real-time alerts via Amazon SNS for critical issues.

---

## 🏗️ Architecture Summary

```text
Application / Service Logs (.json / .jsonl)
                 │
                 ▼
          [Amazon S3 Bucket]
                 │
                 ▼ (S3 Event Notification)
       [AWS Lambda: Log Processor]
                 │
                 ├──► Log Parser & Classifier
                 │
                 ├──► [DynamoDB: cloudlog_events] (All logs)
                 │
                 ├──► [DynamoDB: cloudlog_incidents] (Errors / Incidents)
                 │
                 └──► [Amazon SNS: Critical Topic] (Alert Notifications)
```

For detailed architectural decisions and ADRs, refer to [`docs/architecture.md`](docs/architecture.md).

---

## 📁 Repository Structure

```text
CloudLog/
├── backend/
│   ├── common/         # Shared schemas, config, and utilities
│   ├── ingestion/      # S3 event listener and raw file extractor
│   ├── analyzer/       # Rule-based parser, validator, and classifier
│   ├── incidents/      # Incident generator and lifecycle management
│   └── api/            # API Gateway Lambda routes and query handlers
├── infrastructure/
│   └── terraform/      # Infrastructure as Code (S3, Lambda, DynamoDB, SNS, IAM)
├── tests/
│   ├── unit/           # Fast unit tests (parsers, classifiers, handlers)
│   └── fixtures/       # Sample JSON log files and S3 event payloads
├── docs/               # Architecture documents, ADRs, and API specifications
├── docker/             # Docker configurations (e.g. local log generator)
├── pyproject.toml      # Python project configuration & pytest setup
├── requirements.txt    # Runtime dependencies (boto3)
├── requirements-dev.txt# Dev & testing tools (pytest, moto, ruff)
└── README.md           # Project documentation
```

---

## 🚀 Quickstart (Local Development)

### 1. Prerequisites
* Python 3.11+ (or 3.14)
* Virtual environment (`venv`)

### 2. Setup Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 3. Run Tests
```bash
pytest
```
