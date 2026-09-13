"""
REST API Lambda Handler for CloudLog Dashboard.
Routes incoming HTTP API Gateway v2 requests to DynamoDB repositories,
enforces Role-Based Access Control (RBAC), and returns clean JSON responses with CORS.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from backend.api.auth import extract_user_context
from backend.common.events_repository import EventsRepository
from backend.incidents.repository import IncidentsRepository

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,PATCH,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-User-Role",
    "Content-Type": "application/json",
}


def _json_response(status_code: int, data: Any) -> Dict[str, Any]:
    """Helper to format standard API Gateway v2 HTTP proxy responses."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(data),
    }


def handle_api_request(
    event: Dict[str, Any],
    events_repo: Optional[EventsRepository] = None,
    incidents_repo: Optional[IncidentsRepository] = None,
) -> Dict[str, Any]:
    """
    Route and dispatch an API Gateway HTTP API v2 request.

    Args:
        event: API Gateway 2.0 proxy event dictionary.
        events_repo: Optional EventsRepository instance (injected for testing/mocking).
        incidents_repo: Optional IncidentsRepository instance (injected for testing/mocking).

    Returns:
        API Gateway HTTP proxy response dictionary with statusCode, headers, and body.
    """
    http_ctx = event.get("requestContext", {}).get("http", {})
    method = http_ctx.get("method", event.get("httpMethod", "GET")).upper()
    path = event.get("rawPath") or http_ctx.get("path") or event.get("path", "/")

    # 1. Handle CORS Preflight
    if method == "OPTIONS":
        return _json_response(200, {"message": "CORS preflight OK"})

    # Initialize repositories if not injected
    e_repo = events_repo or EventsRepository()
    i_repo = incidents_repo or IncidentsRepository()

    query_params = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}
    user = extract_user_context(event)

    logger.info("API Request: %s %s (User: %s, Role: %s)", method, path, user.email, user.role)

    # Normalize path (remove trailing slash if not root)
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    try:
        # -------------------------------------------------------------
        # 2. GET /statistics
        # -------------------------------------------------------------
        if method == "GET" and path == "/statistics":
            stats = e_repo.get_statistics()
            open_incidents = i_repo.get_open_incidents(limit=100)
            stats["open_incidents_count"] = len(open_incidents)
            stats["recent_open_incidents"] = [inc.to_dynamodb_item() for inc in open_incidents[:5]]
            return _json_response(200, stats)

        # -------------------------------------------------------------
        # 3. GET /services
        # -------------------------------------------------------------
        if method == "GET" and path == "/services":
            services = e_repo.get_services()
            return _json_response(200, {"services": services, "count": len(services)})

        # -------------------------------------------------------------
        # 4. GET /events/critical
        # -------------------------------------------------------------
        if method == "GET" and path == "/events/critical":
            limit = int(query_params.get("limit", 50))
            events = e_repo.scan_recent_events(limit=limit, level="CRITICAL")
            return _json_response(200, {
                "events": [e.to_dynamodb_item() for e in events],
                "count": len(events),
            })

        # -------------------------------------------------------------
        # 5. GET /events
        # -------------------------------------------------------------
        if method == "GET" and path == "/events":
            limit = int(query_params.get("limit", 50))
            level = query_params.get("level")
            service = query_params.get("service")

            events = e_repo.scan_recent_events(limit=limit, level=level, service=service)
            return _json_response(200, {
                "events": [e.to_dynamodb_item() for e in events],
                "count": len(events),
            })

        # -------------------------------------------------------------
        # 6. GET /incidents
        # -------------------------------------------------------------
        if method == "GET" and path == "/incidents":
            limit = int(query_params.get("limit", 50))
            status_filter = query_params.get("status")

            if status_filter == "OPEN":
                incidents = i_repo.get_open_incidents(limit=limit)
            else:
                incidents = i_repo.get_all_incidents(limit=limit)
                if status_filter:
                    incidents = [i for i in incidents if i.status == status_filter]

            return _json_response(200, {
                "incidents": [i.to_dynamodb_item() for i in incidents],
                "count": len(incidents),
            })

        # -------------------------------------------------------------
        # 7. GET /incidents/{id}
        # -------------------------------------------------------------
        if method == "GET" and (path.startswith("/incidents/") and len(path.split("/")) == 3):
            incident_id = path_params.get("id") or path.split("/")[2]
            incident = i_repo.get_incident(incident_id)
            if not incident:
                return _json_response(404, {"error": f"Incident '{incident_id}' not found"})
            return _json_response(200, {"incident": incident.to_dynamodb_item()})

        # -------------------------------------------------------------
        # 8. PATCH /incidents/{id} (Resolve Incident)
        # -------------------------------------------------------------
        if method == "PATCH" and (path.startswith("/incidents/") and len(path.split("/")) == 3):
            # RBAC Enforcement: Viewers cannot modify incidents
            if not user.can_modify_incidents:
                return _json_response(403, {
                    "error": f"Forbidden: User role '{user.role}' is not authorized to modify incidents.",
                    "required_roles": ["Admin", "Analyst"],
                })

            incident_id = path_params.get("id") or path.split("/")[2]
            body_raw = event.get("body") or "{}"
            try:
                body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
            except json.JSONDecodeError:
                return _json_response(400, {"error": "Invalid JSON payload in request body"})

            resolved = i_repo.resolve_incident(
                incident_id=incident_id,
                resolved_by=user.email or user.user_id,
            )
            if not resolved:
                return _json_response(404, {"error": f"Incident '{incident_id}' not found"})

            logger.info("Incident %s resolved by %s (%s)", incident_id, user.email, user.role)
            return _json_response(200, {
                "message": f"Incident '{incident_id}' resolved successfully",
                "incident": resolved.to_dynamodb_item(),
            })

        # -------------------------------------------------------------
        # 9. POST /simulate (Emit Telemetry & Trigger Incident)
        # -------------------------------------------------------------
        if method == "POST" and path == "/simulate":
            # Only Admin or Analyst can simulate logs
            if not user.can_modify_incidents:
                return _json_response(403, {
                    "error": f"Forbidden: User role '{user.role}' is not authorized to simulate logs.",
                    "required_roles": ["Admin", "Analyst"],
                })

            body_raw = event.get("body") or "{}"
            try:
                body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
            except json.JSONDecodeError:
                return _json_response(400, {"error": "Invalid JSON payload in request body"})

            service = body.get("service") or "payment-gateway"
            level = body.get("level") or "CRITICAL"
            message = body.get("message") or f"[{service}] Simulated {level} outage emitted from dashboard"
            error_code = body.get("error_code")
            if not error_code and level in ("ERROR", "CRITICAL"):
                error_code = f"{level}_SIMULATED_ALERT"

            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": service,
                "level": level,
                "message": message,
                "request_id": f"req-{uuid.uuid4().hex[:12]}",
            }
            if error_code:
                log_entry["error_code"] = error_code

            # Upload to S3 to trigger real serverless pipeline
            s3_bucket = os.environ.get("S3_LOG_BUCKET") or os.environ.get("S3_BUCKET_NAME")
            if not s3_bucket:
                return _json_response(500, {"error": "S3_LOG_BUCKET environment variable not set"})

            s3_client = boto3.client("s3")
            s3_key = f"raw-logs/simulations/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/sim-{uuid.uuid4().hex[:8]}.jsonl"
            jsonl_data = json.dumps(log_entry) + "\n"

            s3_client.put_object(
                Bucket=s3_bucket,
                Key=s3_key,
                Body=jsonl_data.encode("utf-8"),
                ContentType="application/x-ndjson",
            )

            logger.info("Simulated log uploaded to s3://%s/%s by %s", s3_bucket, s3_key, user.email)
            return _json_response(201, {
                "message": "Simulated log uploaded to S3. Pipeline processing initiated.",
                "log": log_entry,
                "s3_uri": f"s3://{s3_bucket}/{s3_key}",
            })

        # -------------------------------------------------------------
        # 10. Fallback 404 Route
        # -------------------------------------------------------------
        return _json_response(404, {
            "error": f"Route not found: {method} {path}",
            "available_endpoints": [
                "GET /events",
                "GET /events/critical",
                "GET /incidents",
                "GET /incidents/{id}",
                "PATCH /incidents/{id}",
                "GET /statistics",
                "GET /services",
                "POST /simulate",
            ],
        })

    except Exception as exc:
        logger.exception("Internal API error processing %s %s: %s", method, path, exc)
        return _json_response(500, {"error": f"Internal server error: {str(exc)}"})


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Standard AWS Lambda execution entry point for API Gateway.
    """
    return handle_api_request(event=event)
