#!/usr/bin/env python3
"""
End-to-end check of a real AWS deployment (run after `terraform apply`).

    .venv/bin/python scripts/test_e2e_aws.py

  1. signs in to Cognito as the demo Analyst and Viewer
  2. runs the database-outage scenario through API Gateway (-> S3 -> Lambda)
  3. waits for the processor's pipeline-run record
  4. checks incidents were opened and an SNS alert was published
  5. checks the Viewer is refused (403) when trying to change anything
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

TF = Path(__file__).resolve().parents[1] / "infrastructure" / "terraform"
ACCOUNTS = {"Analyst": ("analyst@cloudlog.local", "CloudLogAnalyst#2026"),
            "Viewer": ("viewer@cloudlog.local", "CloudLogViewer#2026")}


def tf(name: str) -> str:
    return subprocess.run(["terraform", "output", "-raw", name], cwd=TF, capture_output=True,
                          text=True, check=True).stdout.strip()


def token(client_id: str, region: str, role: str) -> str:
    user, password = ACCOUNTS[role]
    auth = boto3.client("cognito-idp", region_name=region).initiate_auth(
        ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": user, "PASSWORD": password})
    return auth["AuthenticationResult"]["IdToken"]


def call(base: str, jwt: str, method: str, path: str, body=None):
    req = urllib.request.Request(base.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f'  ({detail})' if detail else ''}")
    if not ok:
        sys.exit(1)


def main() -> None:
    region, base, client_id = tf("aws_region"), tf("api_gateway_endpoint"), tf("cognito_user_pool_client_id")
    print(f"CloudLog end-to-end test against {base}")
    analyst, viewer = token(client_id, region, "Analyst"), token(client_id, region, "Viewer")
    check("Cognito issued tokens for Analyst and Viewer", bool(analyst and viewer))

    status, me = call(base, analyst, "GET", "/me")
    check("JWT authorizer accepts the token and maps the role",
          status == 200 and me["role"] == "Analyst", me.get("role"))

    status, sim = call(base, analyst, "POST", "/simulator/runs", {"scenario": "db-outage"})
    check("API uploaded the scenario file to S3", status == 201, sim.get("s3_uri"))

    run = None
    for _ in range(30):
        time.sleep(1)
        _, runs = call(base, analyst, "GET", "/pipeline/runs?limit=10")
        run = next((r for r in runs["runs"] if r["s3_uri"] == sim["s3_uri"]), None)
        if run:
            break
    check("S3 event invoked the processor Lambda", run is not None)
    check("Processor stored every line", run["stored"] == len(sim["lines"]) and run["rejected"] == 0,
          f"{run['stored']} stored in {run['duration_ms']} ms")
    check("Detection rules opened or updated incidents", len(run["detections"]) >= 3, f"{len(run['detections'])}")
    already_open = any(d["severity"] == "CRITICAL" and d["outcome"] == "updated" for d in run["detections"])
    check("SNS alert published for the critical failure", bool(run["alerts"]) or already_open,
          f"{len(run['alerts'])} alerts" + (", critical incident was already open" if already_open else ""))

    status, incidents = call(base, analyst, "GET", "/incidents?status=OPEN")
    check("Open incidents are queryable via the status GSI", status == 200 and incidents["count"] > 0)
    target = incidents["incidents"][0]["incident_id"]

    status, _ = call(base, viewer, "PATCH", f"/incidents/{target}", {"action": "resolve"})
    check("Viewer is refused when resolving", status == 403)
    status, _ = call(base, viewer, "POST", "/simulator/runs", {"scenario": "oom-crash"})
    check("Viewer is refused when simulating", status == 403)

    status, _ = call(base, analyst, "GET", "/overview")
    check("Overview analytics computed", status == 200)
    print("All checks passed.")


if __name__ == "__main__":
    main()
