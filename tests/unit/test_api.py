import json

import pytest

from backend.handlers.api import Api
from backend.handlers.auth import user_from_event
from backend.handlers.processor import Processor
from backend.util import now_iso
from tests.conftest import jsonl, log


def request(method, path, role=None, body=None, query=None, claims=None):
    event = {"rawPath": path, "requestContext": {"http": {"method": method}},
             "headers": {}, "queryStringParameters": query}
    if role and claims is None:
        claims = {"sub": "u-1", "email": f"{role.lower()}@x", "cognito:groups": [role]}
    if claims:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def call(api, *args, **kwargs):
    response = api.handle(request(*args, **kwargs))
    return response["statusCode"], json.loads(response["body"])


@pytest.fixture
def api(aws):
    return Api(s3=aws.s3)


@pytest.fixture
def seeded(aws, api):
    aws.s3.put_object(Bucket=aws.names["bucket"], Key="raw-logs/seed.jsonl", Body=jsonl(
        log(ts=now_iso()),
        log(level="ERROR", message="Card capture timed out", error_code="PGW", service="payments", ts=now_iso()),
        log(level="CRITICAL", message="Primary down", service="db", ts=now_iso()),
    ).encode())
    Processor(s3=aws.s3).process_file(aws.names["bucket"], "raw-logs/seed.jsonl")
    return api


# ------------------------------------------------------------------ auth & routing
@pytest.mark.parametrize("groups, role", [
    (["Admin", "Viewer"], "Admin"), ("Analyst", "Analyst"), ("[Analyst Viewer]", "Analyst"),
    ([], "Viewer"), ("nonsense", "Viewer"),
])
def test_role_comes_from_cognito_groups(groups, role):
    event = request("GET", "/me", claims={"sub": "1", "email": "a@x", "cognito:groups": groups})
    assert user_from_event(event).role == role


def test_dev_role_header_is_ignored_outside_the_emulator(monkeypatch):
    event = {"headers": {"X-User-Role": "Admin"}}
    assert user_from_event(event).role == "Viewer"
    monkeypatch.setenv("CLOUDLOG_LOCAL_MODE", "1")
    assert user_from_event(event).role == "Admin"


@pytest.mark.parametrize("role, method, path, body, allowed", [
    ("Viewer", "GET", "/overview", None, True),
    ("Viewer", "PATCH", "/incidents/inc_x", {"action": "resolve"}, False),
    ("Viewer", "POST", "/simulator/runs", {"scenario": "oom-crash"}, False),
    ("Analyst", "POST", "/simulator/runs", {"scenario": "oom-crash"}, True),
    ("Analyst", "POST", "/admin/reset", None, False),
    ("Admin", "POST", "/admin/reset", None, True),
])
def test_rbac_matrix(api, role, method, path, body, allowed):
    status, _ = call(api, method, path, role, body)
    assert (status != 403) is allowed


def test_me_reports_permissions(api):
    assert call(api, "GET", "/me", "Analyst")[1]["permissions"] == ["read", "simulate", "triage"]


def test_unknown_route_preflight_and_bad_json(api):
    assert call(api, "GET", "/nope", "Admin")[0] == 404
    assert api.handle(request("OPTIONS", "/events"))["statusCode"] == 204
    bad = request("POST", "/simulator/runs", "Admin")
    bad["body"] = "{oops"
    assert api.handle(bad)["statusCode"] == 400
    assert api.handle(request("GET", "/events", "Admin"))["headers"]["Access-Control-Allow-Origin"] == "*"


# ------------------------------------------------------------------ read endpoints
def test_overview_and_events(seeded):
    status, overview = call(seeded, "GET", "/overview", "Viewer")
    assert status == 200
    assert overview["totals"]["events"] == 3
    assert overview["incidents"]["open"] == 2 and overview["incidents"]["critical_active"] == 1
    assert {s["service"]: s["status"] for s in overview["services"]}["db"] == "down"

    assert call(seeded, "GET", "/events", "Viewer", query={"level": "ERROR"})[1]["count"] == 1
    assert call(seeded, "GET", "/events", "Viewer", query={"service": "db"})[1]["count"] == 1
    assert call(seeded, "GET", "/events", "Viewer", query={"q": "capture"})[1]["count"] == 1
    assert call(seeded, "GET", "/events", "Viewer", query={"level": "LOUD"})[0] == 400
    assert call(seeded, "GET", "/events", "Viewer", query={"limit": "x"})[0] == 400


def test_incident_list_detail_and_triage(seeded):
    _, listing = call(seeded, "GET", "/incidents", "Viewer", query={"status": "OPEN"})
    assert listing["count"] == 2
    assert "source_files" not in listing["incidents"][0]
    incident_id = next(i["incident_id"] for i in listing["incidents"] if i["service"] == "payments")

    _, detail = call(seeded, "GET", f"/incidents/{incident_id}", "Viewer")
    assert detail["incident"]["source_file_count"] == 1
    assert [e["message"] for e in detail["events"]] == ["Card capture timed out"]

    assert call(seeded, "PATCH", f"/incidents/{incident_id}", "Analyst", {"action": "acknowledge"})[0] == 200
    assert call(seeded, "PATCH", f"/incidents/{incident_id}", "Analyst", {"action": "acknowledge"})[0] == 409
    status, body = call(seeded, "PATCH", f"/incidents/{incident_id}", "Analyst", {"action": "resolve", "note": "ok"})
    assert status == 200 and body["incident"]["resolved_by"] == "analyst@x"
    assert call(seeded, "PATCH", "/incidents/inc_nope", "Analyst", {"action": "resolve"})[0] == 404
    assert call(seeded, "PATCH", f"/incidents/{incident_id}", "Analyst", {"action": "delete"})[0] == 400
    assert call(seeded, "GET", "/incidents", "Viewer", query={"status": "WEIRD"})[0] == 400
    assert call(seeded, "GET", "/incidents/inc_nope", "Viewer")[0] == 404


def test_runs_rules_and_scenarios(seeded):
    assert call(seeded, "GET", "/pipeline/runs", "Viewer")[1]["runs"][0]["stored"] == 3
    assert len(call(seeded, "GET", "/rules", "Viewer")[1]["rules"]) == 5
    scenarios = call(seeded, "GET", "/simulator/scenarios", "Viewer")[1]["scenarios"]
    assert "build" not in scenarios[0] and {"id", "name", "expect", "rules"} <= set(scenarios[0])


# ------------------------------------------------------------------ write endpoints
def test_simulation_uploads_a_jsonl_file_to_s3(aws, api):
    status, body = call(api, "POST", "/simulator/runs", "Analyst", {"scenario": "brute-force"})
    assert status == 201 and body["s3_key"].startswith("raw-logs/simulations/")
    obj = aws.s3.get_object(Bucket=aws.names["bucket"], Key=body["s3_key"])
    assert obj["Metadata"] == {"scenario": "brute-force", "triggered-by": "analyst@x"}
    assert len(obj["Body"].read().decode().strip().splitlines()) == len(body["lines"]) == 8


def test_custom_simulation_and_validation(aws, api):
    status, body = call(api, "POST", "/simulator/runs", "Analyst",
                        {"custom": {"service": "svc", "level": "error", "message": "boom", "repeat": 3}})
    assert status == 201 and len(body["lines"]) == 3 and json.loads(body["lines"][0])["level"] == "ERROR"
    assert call(api, "POST", "/simulator/runs", "Analyst", {"custom": {"service": "s", "message": "m"}})[0] == 400
    assert call(api, "POST", "/simulator/runs", "Analyst", {"scenario": "nope"})[0] == 400


def test_simulation_needs_a_bucket(api, monkeypatch):
    monkeypatch.setenv("S3_LOG_BUCKET", "")
    assert call(api, "POST", "/simulator/runs", "Admin", {"scenario": "oom-crash"})[0] == 500


def test_admin_reset_clears_everything(seeded):
    status, body = call(seeded, "POST", "/admin/reset", "Admin")
    assert status == 201 and body["deleted"] == {"events": 3, "incidents": 2, "runs": 1}
    assert call(seeded, "GET", "/overview", "Admin")[1]["totals"]["events"] == 0
