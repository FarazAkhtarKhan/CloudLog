"""
Lambda #2 - Dashboard API (behind API Gateway HTTP API + Cognito JWT authorizer).

Routes                              Permission
  GET   /me                         read
  GET   /overview                   read      MapReduce analytics over the last 24h
  GET   /events                     read      ?level &service &q &fingerprint &limit
  GET   /incidents                  read      ?status &limit
  GET   /incidents/{id}             read      incident + its recent log lines
  PATCH /incidents/{id}             triage    {"action": "acknowledge"|"resolve", "note": "..."}
  GET   /pipeline/runs              read      recent processor runs (pipeline trace)
  GET   /rules                      read      detection rules
  GET   /simulator/scenarios        read
  POST  /simulator/runs             simulate  {"scenario": id} or {"custom": {...}} -> uploads to S3
  POST  /admin/reset                reset     deletes all events, incidents and runs
"""
import json
import logging
import re
import uuid
from collections.abc import Callable
from typing import Any

import boto3

from backend.analytics.mapreduce import build_overview
from backend.analyzer.detector import RULES
from backend.config import INCIDENT_STATUSES, SEVERITIES, SIMULATION_PREFIX, aws_region, log_bucket
from backend.handlers.auth import PERMISSIONS, User, user_from_event
from backend.simulator.scenarios import SCENARIOS, catalog, render, render_custom
from backend.storage.events import EventsStore
from backend.storage.incidents import IncidentsStore, InvalidTransition
from backend.storage.runs import RunsStore
from backend.util import now, now_iso, plain

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-User-Role",
    "Content-Type": "application/json",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def respond(status: int, body: Any) -> dict[str, Any]:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(plain(body))}


def public_incident(item: dict[str, Any]) -> dict[str, Any]:
    view = {k: v for k, v in item.items() if k != "source_files"}
    view["source_file_count"] = len(item.get("source_files", ()))
    return view


def _limit(query: dict[str, str], default: int, maximum: int = 200) -> int:
    try:
        return max(1, min(int(query.get("limit", default)), maximum))
    except ValueError:
        raise ApiError(400, "'limit' must be a number") from None


class Api:
    def __init__(self, events: EventsStore | None = None, incidents: IncidentsStore | None = None,
                 runs: RunsStore | None = None, s3=None):
        self.events = events or EventsStore()
        self.incidents = incidents or IncidentsStore()
        self.runs = runs or RunsStore()
        self._s3 = s3
        self.routes: list[tuple[str, re.Pattern, str, Callable]] = [
            ("GET", re.compile(r"^/me$"), "read", self.me),
            ("GET", re.compile(r"^/overview$"), "read", self.overview),
            ("GET", re.compile(r"^/events$"), "read", self.list_events),
            ("GET", re.compile(r"^/incidents$"), "read", self.list_incidents),
            ("GET", re.compile(r"^/incidents/(?P<id>[\w-]+)$"), "read", self.get_incident),
            ("PATCH", re.compile(r"^/incidents/(?P<id>[\w-]+)$"), "triage", self.update_incident),
            ("GET", re.compile(r"^/pipeline/runs$"), "read", self.list_runs),
            ("GET", re.compile(r"^/rules$"), "read", lambda **_: {"rules": RULES}),
            ("GET", re.compile(r"^/simulator/scenarios$"), "read", lambda **_: {"scenarios": catalog()}),
            ("POST", re.compile(r"^/simulator/runs$"), "simulate", self.simulate),
            ("POST", re.compile(r"^/admin/reset$"), "reset", self.reset),
        ]

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=aws_region())
        return self._s3

    # ---------------------------------------------------------------- dispatch
    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        http = event.get("requestContext", {}).get("http", {})
        method = http.get("method", "GET").upper()
        path = (event.get("rawPath") or http.get("path") or "/").rstrip("/") or "/"
        if method == "OPTIONS":
            return respond(204, {})

        user = user_from_event(event)
        query = event.get("queryStringParameters") or {}
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return respond(400, {"error": "Request body is not valid JSON"})

        for route_method, pattern, permission, fn in self.routes:
            match = pattern.match(path)
            if not match or route_method != method:
                continue
            if not user.can(permission):
                return respond(403, {"error": f"The {user.role} role cannot do this. "
                                              f"It needs the '{permission}' permission."})
            try:
                logger.info("%s %s by %s (%s)", method, path, user.email, user.role)
                result = fn(user=user, query=query, body=body, **match.groupdict())
                status = 201 if method == "POST" else 200
                return respond(status, result)
            except ApiError as exc:
                return respond(exc.status, {"error": str(exc)})
            except Exception:
                logger.exception("Unhandled error on %s %s", method, path)
                return respond(500, {"error": "Internal error. Check the API Lambda logs in CloudWatch."})
        return respond(404, {"error": f"No route for {method} {path}"})

    # ---------------------------------------------------------------- handlers
    def me(self, user: User, **_) -> dict[str, Any]:
        return {"email": user.email, "role": user.role, "permissions": sorted(PERMISSIONS[user.role])}

    def overview(self, **_) -> dict[str, Any]:
        incidents = self.incidents.list(limit=500)
        return build_overview(self.events.since(hours=24), incidents)

    def list_events(self, query: dict[str, str], **_) -> dict[str, Any]:
        level = query.get("level", "").upper() or None
        if level and level not in SEVERITIES:
            raise ApiError(400, f"'level' must be one of {', '.join(SEVERITIES)}")
        events = self.events.recent(
            limit=_limit(query, 50), level=level, service=query.get("service") or None,
            search=query.get("q") or None, fingerprint=query.get("fingerprint") or None,
        )
        return {"events": events, "count": len(events)}

    def list_incidents(self, query: dict[str, str], **_) -> dict[str, Any]:
        status = query.get("status", "").upper() or None
        if status and status not in INCIDENT_STATUSES:
            raise ApiError(400, f"'status' must be one of {', '.join(INCIDENT_STATUSES)}")
        items = self.incidents.list(status=status, limit=_limit(query, 50))
        return {"incidents": [public_incident(i) for i in items], "count": len(items)}

    def get_incident(self, id: str, **_) -> dict[str, Any]:
        item = self.incidents.get(id)
        if not item:
            raise ApiError(404, f"Incident {id} does not exist")
        related = self.events.recent(limit=25, service=item["service"],
                                     fingerprint=item.get("log_fingerprint", item["fingerprint"]))
        return {"incident": public_incident(item), "events": related}

    def update_incident(self, id: str, user: User, body: dict[str, Any], **_) -> dict[str, Any]:
        action, note = body.get("action"), str(body.get("note", ""))[:500]
        if action not in ("acknowledge", "resolve"):
            raise ApiError(400, "'action' must be 'acknowledge' or 'resolve'")
        try:
            fn = self.incidents.acknowledge if action == "acknowledge" else self.incidents.resolve
            item = fn(id, by=user.email, note=note)
        except InvalidTransition as exc:
            raise ApiError(409, str(exc)) from exc
        if item is None:
            raise ApiError(404, f"Incident {id} does not exist")
        return {"incident": public_incident(item)}

    def list_runs(self, query: dict[str, str], **_) -> dict[str, Any]:
        runs = self.runs.recent(limit=_limit(query, 20, maximum=100))
        return {"runs": runs, "count": len(runs)}

    def simulate(self, user: User, body: dict[str, Any], **_) -> dict[str, Any]:
        bucket = log_bucket()
        if not bucket:
            raise ApiError(500, "S3_LOG_BUCKET is not configured on the API Lambda")

        if body.get("custom"):
            c = body["custom"]
            level = str(c.get("level", "")).upper()
            if not c.get("service") or not c.get("message") or level not in SEVERITIES:
                raise ApiError(400, "Custom logs need 'service', 'message' and a valid 'level'")
            repeat = max(1, min(int(c.get("repeat", 1)), 20))
            scenario_id = "custom"
            lines = render_custom(str(c["service"])[:60], level, str(c["message"])[:500],
                                  (c.get("error_code") or "")[:60] or None, repeat)
        else:
            scenario_id = body.get("scenario")
            if scenario_id not in SCENARIOS:
                raise ApiError(400, f"Unknown scenario '{scenario_id}'")
            lines = render(scenario_id)

        key = f"{SIMULATION_PREFIX}{now().strftime('%Y/%m/%d')}/{scenario_id}-{uuid.uuid4().hex[:8]}.jsonl"
        self.s3.put_object(
            Bucket=bucket, Key=key, Body=("\n".join(lines) + "\n").encode("utf-8"),
            ContentType="application/x-ndjson",
            Metadata={"scenario": scenario_id, "triggered-by": user.email},
        )
        logger.info("Uploaded simulation %s (%d lines) to s3://%s/%s", scenario_id, len(lines), bucket, key)
        return {"scenario": scenario_id, "s3_uri": f"s3://{bucket}/{key}", "s3_key": key,
                "uploaded_at": now_iso(), "lines": lines}

    def reset(self, user: User, **_) -> dict[str, Any]:
        deleted = {"events": self.events.purge(), "incidents": self.incidents.purge(), "runs": self.runs.purge()}
        logger.warning("Demo data reset by %s: %s", user.email, deleted)
        return {"deleted": deleted}


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    return Api().handle(event)
