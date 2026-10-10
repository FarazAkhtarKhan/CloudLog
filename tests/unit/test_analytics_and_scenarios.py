from datetime import timedelta

import pytest

from backend.analytics.mapreduce import TIMELINE_MINUTES, build_overview, map_reduce, sum_reducer
from backend.analyzer.detector import detect
from backend.analyzer.parser import parse_lines
from backend.simulator.scenarios import SCENARIOS, catalog, render, render_custom
from backend.util import iso, now


# ------------------------------------------------------------------ MapReduce
def test_generic_map_reduce_word_count():
    words = ["error", "info", "error"]
    assert map_reduce(words, lambda w: [((w,), 1)], sum_reducer) == {("error",): 2, ("info",): 1}


def _event(level, service="svc", minutes_ago=0, code=None):
    e = {"level": level, "service": service, "timestamp": iso(now() - timedelta(minutes=minutes_ago))}
    if code:
        e["error_code"] = code
    return e


def _incident(status, severity="ERROR", service="svc", created="2026-10-10T10:00:00.000Z", **kw):
    return {"status": status, "severity": severity, "service": service, "created_at": created, **kw}


def test_overview_totals_timeline_services_and_top_errors():
    events = [_event("INFO"), _event("INFO", minutes_ago=2), _event("ERROR", code="E1"),
              _event("ERROR", code="E1"), _event("CRITICAL", service="db", code="DOWN"),
              _event("WARNING", minutes_ago=300)]  # outside the 60-minute timeline
    incidents = [_incident("OPEN", "CRITICAL", "db"), _incident("ACKNOWLEDGED", service="api")]
    o = build_overview(events, incidents)

    assert o["totals"]["events"] == 6
    assert o["totals"]["error_rate"] == 50.0
    assert len(o["timeline"]) == TIMELINE_MINUTES
    assert sum(sum(m[lvl] for lvl in ("INFO", "WARNING", "ERROR", "CRITICAL")) for m in o["timeline"]) == 5
    status = {s["service"]: s["status"] for s in o["services"]}
    assert status == {"db": "down", "api": "degraded", "svc": "healthy"}
    assert o["services"][-1]["service"] == "svc"  # unhealthy services listed first
    assert o["top_errors"][0] == {"error_code": "E1", "service": "svc", "count": 2}


def test_mtta_and_mttr_in_minutes():
    incidents = [
        _incident("RESOLVED", acknowledged_at="2026-10-10T10:04:00.000Z", resolved_at="2026-10-10T10:20:00.000Z"),
        _incident("RESOLVED", acknowledged_at="2026-10-10T10:02:00.000Z", resolved_at="2026-10-10T10:10:00.000Z"),
    ]
    stats = build_overview([], incidents)["incidents"]
    assert (stats["mtta_minutes"], stats["mttr_minutes"], stats["resolved"]) == (3.0, 15.0, 2)
    assert build_overview([], [])["incidents"]["mttr_minutes"] is None


# ------------------------------------------------------------------ Scenarios
@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_each_scenario_triggers_exactly_the_rules_it_advertises(scenario_id):
    batch = parse_lines(render(scenario_id), "b", f"{scenario_id}.jsonl")
    fired = {d.rule_id for d in detect(batch.events)}
    advertised = set(SCENARIOS[scenario_id]["rules"]) - {"escalation"}  # escalation needs a second run
    assert fired == advertised


def test_malformed_file_rejects_five_lines():
    batch = parse_lines(render("malformed-file"), "b", "k.jsonl")
    assert (len(batch.events), len(batch.rejections)) == (4, 5)


def test_payment_scenario_messages_are_masked():
    batch = parse_lines(render("payment-timeouts"), "b", "k.jsonl")
    errors = [e for e in batch.events if e.level == "ERROR"]
    assert all(e.pii_redacted and "@example" in e.message and "***" in e.message for e in errors)


def test_catalog_and_custom_logs():
    assert {s["id"] for s in catalog()} == set(SCENARIOS)
    lines = render_custom("svc", "ERROR", "boom", "E1", repeat=2)
    assert len(parse_lines(lines, "b", "k.jsonl").events) == 2
