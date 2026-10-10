"""
Failure scenarios for the simulator.

Each scenario writes a realistic JSONL log file. The API uploads it to S3, which
fires the real processor Lambda - nothing is short-circuited. Every scenario is
designed to exercise one or more detection rules so the result is predictable.
"""
import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from backend.util import iso, now

Line = dict[str, Any]


def _req() -> str:
    return "req-" + uuid.uuid4().hex[:12]


def _log(service: str, level: str, message: str, code: str | None = None, **extra) -> Line:
    line: Line = {"service": service, "level": level, "message": message, "request_id": _req()}
    if code:
        line["error_code"] = code
    line.update(extra)
    return line


def healthy_traffic() -> list[Line]:
    users = ["u-1042", "u-2291", "u-3310", "u-0815"]
    return [
        _log("auth-service", "INFO", f"Session issued for {random.choice(users)}", endpoint="/auth/login"),
        _log("order-service", "INFO", f"Order ORD-{random.randint(10000, 99999)} created", endpoint="/orders"),
        _log("payment-gateway", "INFO", "Card authorised in 182ms", endpoint="/payments/capture"),
        _log("inventory-service", "INFO", "Stock reserved for SKU-2231 (qty 2)"),
        _log("notification-worker", "INFO", "Order confirmation email queued"),
        _log("order-service", "INFO", f"Order ORD-{random.randint(10000, 99999)} created", endpoint="/orders"),
        _log("checkout-api", "INFO", "GET /cart 200 in 41ms", endpoint="/cart"),
        _log("auth-service", "INFO", f"Token refreshed for {random.choice(users)}", endpoint="/auth/refresh"),
        _log("inventory-service", "INFO", "Nightly stock sync finished: 1,204 SKUs"),
        _log("checkout-api", "INFO", "POST /checkout 201 in 233ms", endpoint="/checkout"),
    ]


def db_outage() -> list[Line]:
    return [
        _log("database-cluster", "WARNING", "Connection pool usage at 86%", "DB_POOL_SATURATED"),
        _log("database-cluster", "WARNING", "Connection pool usage at 93%", "DB_POOL_SATURATED"),
        _log("order-service", "ERROR", "Query timed out after 5000ms on orders.insert", "DB_QUERY_TIMEOUT",
             endpoint="/orders"),
        _log("database-cluster", "WARNING", "Connection pool usage at 99%", "DB_POOL_SATURATED"),
        _log("inventory-service", "ERROR", "Query timed out after 5000ms on stock.update", "DB_QUERY_TIMEOUT"),
        _log("order-service", "ERROR", "Query timed out after 5003ms on orders.insert", "DB_QUERY_TIMEOUT",
             endpoint="/orders"),
        _log("database-cluster", "CRITICAL", "Primary node db-primary-1 unreachable; automatic failover started",
             "DB_PRIMARY_DOWN"),
    ]


def payment_timeouts() -> list[Line]:
    customers = ["priya.sharma@example.com", "j.okafor@example.org", "mei.lin@example.net"]
    lines = [_log("payment-gateway", "INFO", "Card authorised in 204ms", endpoint="/payments/capture")]
    for email in customers:
        lines.append(_log(
            "payment-gateway", "ERROR",
            f"Card capture timed out after {random.randint(5000, 5400)}ms for {email} "
            f"(card 4111 1111 1111 {random.randint(1000, 9999)})",
            "PAYMENT_GATEWAY_TIMEOUT", endpoint="/payments/capture",
        ))
    return lines


def brute_force() -> list[Line]:
    attacker = "203.0.113.42"
    targets = ["admin@shop.example", "ops@shop.example", "root@shop.example", "finance@shop.example"]
    lines = [_log("auth-service", "INFO", "Session issued for u-1042", ip_address="198.51.100.7",
                  endpoint="/auth/login")]
    for i in range(7):
        lines.append(_log("auth-service", "WARNING", f"Login failed for {targets[i % len(targets)]}: bad password",
                          "AUTH_LOGIN_FAILED", ip_address=attacker, endpoint="/auth/login"))
    return lines


def latency_degradation() -> list[Line]:
    return [_log("checkout-api", "WARNING", f"p95 latency {ms}ms exceeds the 800ms objective",
                 "LATENCY_SLO_BREACH", endpoint="/checkout") for ms in (912, 1040, 1287, 1530)]


def malformed_file() -> list[Any]:
    return [
        _log("order-service", "INFO", "Order ORD-55120 created"),
        '{"service": "order-service", "level": "INFO", "message": "truncated li',
        _log("inventory-service", "INFO", "Stock reserved for SKU-9001 (qty 1)"),
        {"service": "billing", "level": "INFO"},                                   # no message
        {"service": "billing", "level": "FATAL", "message": "Unknown level used"},  # bad level
        {"service": "billing", "level": "ERROR", "message": "Bad clock", "timestamp": "yesterday"},
        "",
        _log("checkout-api", "INFO", "GET /cart 200 in 38ms"),
        _log("notification-worker", "INFO", "Push notification delivered"),
    ]


def iot_sensor_fault() -> list[Line]:
    gw = "iot-edge-gateway"
    return [
        _log(gw, "INFO", "MQTT heartbeat from cold-store-03 (4.1°C)", device_id="cold-store-03"),
        _log(gw, "INFO", "MQTT heartbeat from cold-store-07 (5.2°C)", device_id="cold-store-07"),
        _log(gw, "WARNING", "Sensor cold-store-07 reading drifted 1.8°C from its pair", "SENSOR_DRIFT"),
        _log(gw, "ERROR", "Sensor cold-store-11 stopped reporting (last seen 120s ago)", "SENSOR_OFFLINE"),
        _log(gw, "ERROR", "Sensor cold-store-12 stopped reporting (last seen 95s ago)", "SENSOR_OFFLINE"),
        _log(gw, "CRITICAL", "Cold storage zone B at 9.4°C, above the 8°C safety limit", "TEMP_LIMIT_EXCEEDED"),
    ]


def oom_crash() -> list[Line]:
    return [
        _log("notification-worker", "WARNING", "Heap usage 88% of 512MB", "MEMORY_HIGH"),
        _log("notification-worker", "WARNING", "Heap usage 94% of 512MB", "MEMORY_HIGH"),
        _log("notification-worker", "CRITICAL", "Container killed by the OOM killer (exit code 137)",
             "OOM_KILLED"),
    ]


SCENARIOS: dict[str, dict[str, Any]] = {
    "healthy-traffic": {
        "name": "Normal traffic",
        "summary": "Routine INFO logs from six services.",
        "expect": ["Logs stored", "No incidents"],
        "rules": [],
        "build": healthy_traffic,
    },
    "db-outage": {
        "name": "Database outage",
        "summary": "Pool saturation warnings, query timeouts in two services, then the primary goes down.",
        "expect": ["Warning burst incident", "Grouped timeout incidents", "Critical alert via SNS"],
        "rules": ["warning-burst", "error-log", "critical-log"],
        "build": db_outage,
    },
    "payment-timeouts": {
        "name": "Payment timeouts",
        "summary": "Three card captures time out. Messages contain customer emails and card numbers.",
        "expect": ["One incident, 3 occurrences", "PII masked", "Run twice to escalate"],
        "rules": ["error-log", "escalation"],
        "build": payment_timeouts,
    },
    "brute-force": {
        "name": "Brute-force login",
        "summary": "Seven failed logins from one IP address against admin accounts.",
        "expect": ["Security incident", "Critical alert via SNS", "Emails masked"],
        "rules": ["brute-force"],
        "build": brute_force,
    },
    "latency-degradation": {
        "name": "Latency degradation",
        "summary": "Checkout p95 latency breaches its objective four times in a row.",
        "expect": ["Warnings promoted to an error incident"],
        "rules": ["warning-burst"],
        "build": latency_degradation,
    },
    "iot-sensor-fault": {
        "name": "IoT cold-chain fault",
        "summary": "Edge gateway loses two sensors, then a storage zone goes over its temperature limit.",
        "expect": ["Sensor-offline incident", "Critical alert via SNS"],
        "rules": ["error-log", "critical-log"],
        "build": iot_sensor_fault,
    },
    "oom-crash": {
        "name": "Worker out of memory",
        "summary": "Memory climbs on the notification worker until the container is killed.",
        "expect": ["Critical alert via SNS"],
        "rules": ["critical-log"],
        "build": oom_crash,
    },
    "malformed-file": {
        "name": "Malformed log file",
        "summary": "A file with broken JSON, missing fields, an unknown level and a bad timestamp.",
        "expect": ["Valid lines stored", "5 lines rejected with reasons", "No incidents"],
        "rules": [],
        "build": malformed_file,
    },
}


def catalog() -> list[dict[str, Any]]:
    return [{"id": sid, **{k: v for k, v in s.items() if k != "build"}} for sid, s in SCENARIOS.items()]


def _stamp(lines: list[Any], start: datetime) -> list[str]:
    """Spread timestamps over the last few seconds and serialise to JSONL lines."""
    out: list[str] = []
    for i, line in enumerate(lines):
        if isinstance(line, dict):
            line = dict(line)
            line.setdefault("timestamp", iso(start + timedelta(milliseconds=350 * i)))
            out.append(json.dumps(line, ensure_ascii=False))
        else:
            out.append(line)
    return out


def render(scenario_id: str) -> list[str]:
    lines = SCENARIOS[scenario_id]["build"]()
    return _stamp(lines, now() - timedelta(milliseconds=350 * len(lines)))


def render_custom(service: str, level: str, message: str, error_code: str | None = None,
                  repeat: int = 1) -> list[str]:
    line = _log(service, level, message, error_code or None)
    return _stamp([dict(line, request_id=_req()) for _ in range(repeat)], now() - timedelta(seconds=1))

