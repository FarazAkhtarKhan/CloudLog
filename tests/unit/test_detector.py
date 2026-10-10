import json

from backend.analyzer.detector import RULES, detect
from backend.analyzer.parser import parse_lines
from backend.config import BRUTE_FORCE_THRESHOLD, WARNING_BURST_THRESHOLD
from tests.conftest import log


def events(*payloads):
    return parse_lines([json.dumps(p) for p in payloads], "b", "k.jsonl").events


def test_info_and_isolated_warnings_are_not_incidents():
    assert detect(events(log(), log(level="WARNING", message="slow"))) == []


def test_errors_with_the_same_fingerprint_group_into_one_detection():
    found = detect(events(
        log(level="ERROR", message="Timeout after 5001ms", ts="2026-10-10T10:00:01Z"),
        log(level="ERROR", message="Timeout after 5302ms", ts="2026-10-10T10:00:03Z"),
        log(level="ERROR", message="Disk full"),
    ))
    assert sorted(d.count for d in found) == [1, 2]
    grouped = next(d for d in found if d.count == 2)
    assert grouped.rule_id == "error-log"
    assert grouped.first_seen < grouped.last_seen


def test_critical_line_uses_the_critical_rule():
    [d] = detect(events(log(level="CRITICAL", message="Primary DB down", error_code="DB_DOWN")))
    assert (d.rule_id, d.severity, d.error_code) == ("critical-log", "CRITICAL", "DB_DOWN")


def test_warning_burst_needs_the_threshold():
    warn = log(level="WARNING", message="Pool at 90%", error_code="POOL")
    assert detect(events(*[warn] * (WARNING_BURST_THRESHOLD - 1))) == []
    [d] = detect(events(*[warn] * WARNING_BURST_THRESHOLD))
    assert (d.rule_id, d.severity, d.category) == ("warning-burst", "ERROR", "Degradation")


def test_brute_force_from_one_ip_is_a_critical_security_incident():
    attempt = log(level="WARNING", service="auth", message="Login failed", error_code="AUTH_LOGIN_FAILED",
                  ip_address="203.0.113.42")
    [d] = detect(events(*[attempt] * BRUTE_FORCE_THRESHOLD))
    assert (d.rule_id, d.severity, d.category, d.source_ip) == ("brute-force", "CRITICAL", "Security", "203.0.113.42")
    assert d.fingerprint != d.log_fingerprint  # grouped by attacker IP, not by message


def test_failed_logins_spread_over_ips_are_not_brute_force():
    attempts = [log(level="WARNING", message="Login failed", error_code="AUTH_LOGIN_FAILED",
                    ip_address=f"10.0.0.{i}") for i in range(BRUTE_FORCE_THRESHOLD)]
    assert all(d.rule_id != "brute-force" for d in detect(events(*attempts)))


def test_rules_catalogue_is_complete():
    assert {r["id"] for r in RULES} == {"critical-log", "error-log", "brute-force", "warning-burst", "escalation"}
