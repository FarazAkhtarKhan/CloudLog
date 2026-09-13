#!/usr/bin/env python3
"""
CloudLog Sample Log Generator
Generates realistic, production-like JSONL log batches across microservices
with varying severity levels (INFO, WARNING, ERROR, CRITICAL) for demonstration
and end-to-end integration testing.
"""

import argparse
import datetime
import json
import os
import random
import sys
import uuid

SERVICES = [
    "auth-service",
    "order-service",
    "payment-gateway",
    "inventory-service",
    "notification-worker",
    "database-cluster",
]

SCENARIOS = {
    "INFO": [
        ("User session authenticated successfully", None),
        ("Order #10492 placed and pending payment", None),
        ("Inventory check passed for SKU-9941", None),
        ("Email notification queued for customer", None),
        ("Database query cached in memory", None),
    ],
    "WARNING": [
        ("High latency observed in downstream API: 840ms", "WARN_LATENCY_HIGH"),
        ("Database connection pool usage above 80%", "WARN_POOL_SATURATED"),
        ("Redis cache hit ratio dropped below 60%", "WARN_CACHE_DEGRADED"),
        ("Rate limit threshold approached: 92/100 requests", "WARN_RATE_LIMIT"),
    ],
    "ERROR": [
        ("Payment gateway timeout after 5000ms", "ERR_PAYMENT_TIMEOUT"),
        ("Failed to decrement stock for item SKU-2104: lock acquisition timeout", "ERR_INVENTORY_LOCK"),
        ("User registration failed: duplicate unique constraint on email", "ERR_DUPLICATE_KEY"),
        ("Order settlement failed during checkout", "ERR_CHECKOUT_FAILED"),
    ],
    "CRITICAL": [
        ("CRITICAL: Database connection pool fully exhausted. Deadlock detected.", "CRIT_DB_POOL_EMPTY"),
        ("CRITICAL: Payment provider API returning 500 Internal Server Error for all checkout traffic", "CRIT_GATEWAY_OUTAGE"),
        ("CRITICAL: Master database instance read-only failover initiated", "CRIT_DB_FAILOVER"),
        ("CRITICAL: Out of memory killer terminated order-service worker node", "CRIT_OOM_KILLED"),
    ],
}


def generate_log_entry(service=None, level=None, timestamp=None):
    """Generate a single standardized log entry."""
    if not service:
        service = random.choice(SERVICES)

    if not level:
        # Realistic distribution: mostly INFO, some WARNING, fewer ERROR, rare CRITICAL
        weights = [0.70, 0.15, 0.10, 0.05]
        level = random.choices(["INFO", "WARNING", "ERROR", "CRITICAL"], weights=weights)[0]

    template, code = random.choice(SCENARIOS[level])
    if not timestamp:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    entry = {
        "timestamp": timestamp,
        "service": service,
        "level": level,
        "message": f"[{service}] {template}",
    }

    if code:
        entry["error_code"] = code

    entry["request_id"] = f"req-{uuid.uuid4().hex[:12]}"
    return entry


def generate_batch(count=20, include_critical=True, include_error=True):
    """Generate a list of log entries."""
    logs = []
    base_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=count)

    for i in range(count):
        log_time = (base_time + datetime.timedelta(seconds=i * 20)).isoformat()
        logs.append(generate_log_entry(timestamp=log_time))

    # Guarantee at least 1 ERROR and 1 CRITICAL if requested
    if include_error and not any(l["level"] == "ERROR" for l in logs):
        err_entry = generate_log_entry(
            service="payment-gateway",
            level="ERROR",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        logs.append(err_entry)

    if include_critical and not any(l["level"] == "CRITICAL" for l in logs):
        crit_entry = generate_log_entry(
            service="database-cluster",
            level="CRITICAL",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        logs.append(crit_entry)

    return logs


def main():
    default_bucket = os.environ.get("S3_LOG_BUCKET", "cloudlog-raw-be259898")
    parser = argparse.ArgumentParser(description="Generate sample JSONL log batch for CloudLog")
    parser.add_argument("--count", type=int, default=15, help="Number of log entries to generate")
    parser.add_argument("--output", type=str, default=None, help="Output file path (default stdout)")
    parser.add_argument("--s3-bucket", type=str, default=default_bucket, help=f"Upload directly to target S3 bucket (default: {default_bucket})")
    parser.add_argument("--profile", type=str, default="terraform", help="AWS CLI profile for S3 upload")
    parser.add_argument("--service", type=str, default=None, help="Specific service name for a custom log")
    parser.add_argument("--level", type=str, default=None, choices=["INFO", "WARNING", "ERROR", "CRITICAL"], help="Specific level (e.g. CRITICAL to trigger an alert)")
    parser.add_argument("--message", type=str, default=None, help="Custom message for the log entry")
    parser.add_argument("--error-code", type=str, default=None, help="Custom error code for the log entry")
    args = parser.parse_args()

    if args.level or args.message:
        # User specified a custom individual log entry
        service = args.service or "payment-gateway"
        level = args.level or "CRITICAL"
        message = args.message or f"[{service}] Simulated critical failure: downstream outage detected"
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "service": service,
            "level": level,
            "message": message,
            "request_id": f"req-{uuid.uuid4().hex[:12]}",
        }
        if args.error_code:
            entry["error_code"] = args.error_code
        elif level in ("ERROR", "CRITICAL"):
            entry["error_code"] = f"{level}_CUSTOM_ALERT"
        logs = [entry]
    else:
        logs = generate_batch(count=args.count, include_critical=True, include_error=True)

    jsonl_content = "\n".join(json.dumps(entry) for entry in logs) + "\n"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(jsonl_content)
        print(f"[+] Wrote {len(logs)} logs to {args.output}")

    if args.s3_bucket:
        try:
            import boto3
            session = boto3.Session(profile_name=args.profile)
            s3 = session.client("s3")
            key = f"raw-logs/{datetime.datetime.now(datetime.timezone.utc).strftime('%Y/%m/%d')}/batch-{uuid.uuid4().hex[:8]}.jsonl"
            s3.put_object(
                Bucket=args.s3_bucket,
                Key=key,
                Body=jsonl_content.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            print(f"[+] Successfully uploaded {len(logs)} log(s) to s3://{args.s3_bucket}/{key}")
            if any(l.get("level") == "CRITICAL" for l in logs):
                print("[!] CRITICAL event detected in batch: Lambda will create an incident and dispatch an SNS alert!")
            elif any(l.get("level") == "ERROR" for l in logs):
                print("[!] ERROR event detected in batch: Lambda will create an incident!")
        except Exception as e:
            print(f"[-] S3 upload failed: {e}", file=sys.stderr)
            sys.exit(1)

    if not args.output and not args.s3_bucket:
        print(jsonl_content, end="")


if __name__ == "__main__":
    main()
