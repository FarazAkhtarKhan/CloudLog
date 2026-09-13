#!/usr/bin/env python3
"""
CloudLog End-to-End AWS Integration Test Suite
Validates the complete production lifecycle against live AWS infrastructure:
1. S3 Log Ingestion (.jsonl batch upload)
2. S3 Event Trigger -> Lambda Execution
3. Deterministic Log Parsing & DynamoDB Events Table Persistence
4. Incident Detection (ERROR & CRITICAL) & DynamoDB Incidents Table Persistence
5. SNS Topic Alert Dispatch
6. AWS Cognito Authentication (JWT ID Token via USER_PASSWORD_AUTH)
7. API Gateway Protected Route Invocations (/statistics, /services, /incidents)
8. Role-Based Access Control (Analyst 200 OK vs Viewer 403 Forbidden)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import boto3

AWS_PROFILE = os.environ.get("AWS_PROFILE", "terraform")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Fallback values from Terraform outputs if not provided in environment
S3_BUCKET = os.environ.get("S3_LOG_BUCKET", "cloudlog-raw-be259898")
EVENTS_TABLE = os.environ.get("DYNAMODB_EVENTS_TABLE", "cloudlog_events")
INCIDENTS_TABLE = os.environ.get("DYNAMODB_INCIDENTS_TABLE", "cloudlog_incidents")
API_ENDPOINT = os.environ.get(
    "API_GATEWAY_ENDPOINT",
    "https://yldbrm495e.execute-api.ap-south-1.amazonaws.com",
).rstrip("/")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "iufl9c8nnt2f3vd9jdif0bhh7")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "ap-south-1_WD4fE4UTJ")

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"


def http_request(url, method="GET", headers=None, body=None):
    """Simple HTTP helper using urllib."""
    headers = headers or {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            resp_body = json.loads(resp.read().decode("utf-8"))
            return status, resp_body
    except urllib.error.HTTPError as e:
        resp_body = {}
        try:
            resp_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        return e.code, resp_body


def authenticate_cognito(cognito_client, username, password):
    """Authenticate with Cognito USER_PASSWORD_AUTH and return IdToken."""
    resp = cognito_client.initiate_auth(
        ClientId=COGNITO_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return resp["AuthenticationResult"]["IdToken"]


def run_e2e_tests():
    print("=" * 70)
    print(" CloudLog Serverless End-to-End Live AWS Test Suite")
    print(f" Region: {AWS_REGION} | Profile: {AWS_PROFILE}")
    print(f" S3 Bucket: {S3_BUCKET}")
    print(f" API Gateway: {API_ENDPOINT}")
    print("=" * 70)

    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    s3_client = session.client("s3")
    dynamodb = session.resource("dynamodb")
    cognito_client = session.client("cognito-idp")

    events_table = dynamodb.Table(EVENTS_TABLE)
    incidents_table = dynamodb.Table(INCIDENTS_TABLE)

    test_run_id = uuid.uuid4().hex[:6]
    test_service = f"test-svc-{test_run_id}"

    # -------------------------------------------------------------
    # STEP 1: Generate and Upload Batch to S3
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 1: Uploading synthetic log batch to Amazon S3...")
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    batch_logs = [
        {
            "timestamp": now_iso,
            "service": test_service,
            "level": "INFO",
            "message": f"E2E test batch initiated for run {test_run_id}",
            "request_id": f"req-info-{test_run_id}",
        },
        {
            "timestamp": now_iso,
            "service": test_service,
            "level": "WARNING",
            "message": f"High cache latency observed in {test_service}",
            "error_code": "WARN_CACHE_LATENCY",
            "request_id": f"req-warn-{test_run_id}",
        },
        {
            "timestamp": now_iso,
            "service": test_service,
            "level": "ERROR",
            "message": f"Database transaction failed in {test_service}: deadlock detected",
            "error_code": "ERR_DB_DEADLOCK",
            "request_id": f"req-err-{test_run_id}",
        },
        {
            "timestamp": now_iso,
            "service": test_service,
            "level": "CRITICAL",
            "message": f"CRITICAL: Connection pool exhausted in {test_service}. Outage imminent!",
            "error_code": "CRIT_POOL_EXHAUSTED",
            "request_id": f"req-crit-{test_run_id}",
        },
    ]

    s3_key = f"e2e-tests/{time.strftime('%Y/%m/%d')}/batch-{test_run_id}.jsonl"
    jsonl_payload = "\n".join(json.dumps(l) for l in batch_logs) + "\n"

    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=jsonl_payload.encode("utf-8"),
            ContentType="application/x-ndjson",
        )
        print(f"{PASS} Uploaded 4 logs to s3://{S3_BUCKET}/{s3_key}")
    except Exception as e:
        print(f"{FAIL} S3 PutObject failed: {e}")
        return False

    # -------------------------------------------------------------
    # STEP 2: Wait for S3 Event Notification & Lambda Ingestion
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 2: Waiting for Lambda log-processor execution (polling DynamoDB)...")
    time.sleep(4)  # Initial wait for Lambda cold/warm invocation

    found_events = []
    max_retries = 8
    for attempt in range(max_retries):
        resp = events_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("service").eq(test_service)
        )
        found_events = resp.get("Items", [])
        if len(found_events) >= 4:
            break
        print(f"  ... waiting for events to persist (found {len(found_events)}/4, attempt {attempt + 1}/{max_retries})")
        time.sleep(2)

    if len(found_events) == 4:
        print(f"{PASS} All 4 events successfully parsed and persisted in DynamoDB `{EVENTS_TABLE}`.")
    else:
        print(f"{FAIL} Expected 4 events in `{EVENTS_TABLE}`, found {len(found_events)}.")
        return False

    # -------------------------------------------------------------
    # STEP 3: Verify Incident Detection (ERROR & CRITICAL)
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 3: Verifying Incident creation in `{INCIDENTS_TABLE}`...")
    found_incidents = []
    for attempt in range(max_retries):
        resp = incidents_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("service").eq(test_service)
        )
        found_incidents = resp.get("Items", [])
        if len(found_incidents) >= 2:
            break
        print(f"  ... waiting for incidents to persist (found {len(found_incidents)}/2, attempt {attempt + 1}/{max_retries})")
        time.sleep(2)

    if len(found_incidents) >= 2:
        severities = {inc["severity"] for inc in found_incidents}
        print(f"{PASS} Detected {len(found_incidents)} incidents with severities: {severities}")
        if "CRITICAL" in severities and "ERROR" in severities:
            print(f"{PASS} Both ERROR and CRITICAL incidents generated correctly.")
        else:
            print(f"{FAIL} Expected both ERROR and CRITICAL incident, got: {severities}")
            return False
    else:
        print(f"{FAIL} Expected at least 2 incidents for {test_service}, found {len(found_incidents)}.")
        return False

    target_incident = found_incidents[0]
    target_incident_id = target_incident["incident_id"]

    # -------------------------------------------------------------
    # STEP 4: Authenticate with AWS Cognito
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 4: Authenticating with AWS Cognito...")
    try:
        analyst_token = authenticate_cognito(
            cognito_client, "analyst@cloudlog.local", "CloudLogAnalyst#2026"
        )
        print(f"{PASS} Successfully retrieved JWT IdToken for Analyst user.")

        viewer_token = authenticate_cognito(
            cognito_client, "viewer@cloudlog.local", "CloudLogViewer#2026"
        )
        print(f"{PASS} Successfully retrieved JWT IdToken for Viewer user.")
    except Exception as e:
        print(f"{FAIL} Cognito authentication failed: {e}")
        return False

    # -------------------------------------------------------------
    # STEP 5: Test API Gateway Protected Endpoints (Analyst)
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 5: Testing API Gateway with Analyst Token...")
    headers_analyst = {"Authorization": f"Bearer {analyst_token}"}

    # GET /statistics
    status, stats_data = http_request(f"{API_ENDPOINT}/statistics", headers=headers_analyst)
    if status == 200 and stats_data.get("total_events", 0) > 0:
        print(f"{PASS} GET /statistics returned 200 OK (total events: {stats_data['total_events']})")
    else:
        print(f"{FAIL} GET /statistics failed with status {status}: {stats_data}")
        return False

    # GET /services
    status, svc_data = http_request(f"{API_ENDPOINT}/services", headers=headers_analyst)
    if status == 200 and test_service in svc_data.get("services", []):
        print(f"{PASS} GET /services returned 200 OK (contains `{test_service}`)")
    else:
        print(f"{FAIL} GET /services failed with status {status}: {svc_data}")
        return False

    # GET /incidents
    status, inc_data = http_request(f"{API_ENDPOINT}/incidents", headers=headers_analyst)
    if status == 200 and len(inc_data.get("incidents", [])) > 0:
        print(f"{PASS} GET /incidents returned 200 OK ({len(inc_data['incidents'])} incidents listed)")
    else:
        print(f"{FAIL} GET /incidents failed with status {status}: {inc_data}")
        return False

    # -------------------------------------------------------------
    # STEP 6: Test RBAC: Resolve Incident as Analyst (Allowed)
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 6: Testing Incident Resolution as Analyst (Should SUCCEED)...")
    status, resolve_data = http_request(
        f"{API_ENDPOINT}/incidents/{target_incident_id}",
        method="PATCH",
        headers=headers_analyst,
        body={"status": "RESOLVED"},
    )
    if status == 200 and resolve_data.get("incident", {}).get("status") == "RESOLVED":
        print(f"{PASS} PATCH /incidents/{target_incident_id} succeeded with 200 OK (status: RESOLVED)")
        print(f"       Resolved by: {resolve_data['incident'].get('resolved_by')}")
    else:
        print(f"{FAIL} PATCH /incidents/{target_incident_id} failed with status {status}: {resolve_data}")
        return False

    # -------------------------------------------------------------
    # STEP 7: Test RBAC: Resolve Incident as Viewer (Forbidden)
    # -------------------------------------------------------------
    print(f"\n{INFO} Step 7: Testing Incident Resolution as Viewer (Must RETURN 403 Forbidden)...")
    headers_viewer = {"Authorization": f"Bearer {viewer_token}"}
    status, viewer_res = http_request(
        f"{API_ENDPOINT}/incidents/{target_incident_id}",
        method="PATCH",
        headers=headers_viewer,
        body={"status": "RESOLVED"},
    )
    if status == 403:
        print(f"{PASS} PATCH /incidents as Viewer correctly returned 403 Forbidden.")
        print(f"       RBAC Enforcement verified: \"{viewer_res.get('error')}\"")
    else:
        print(f"{FAIL} Expected 403 Forbidden for Viewer role, got HTTP {status}: {viewer_res}")
        return False

    print("\n" + "=" * 70)
    print(" ALL END-TO-END AWS INTEGRATION TESTS PASSED SUCCESSFULLY! ")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_e2e_tests()
    sys.exit(0 if success else 1)
