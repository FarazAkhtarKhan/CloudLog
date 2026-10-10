"""
Dashboard analytics written in the MapReduce style.

  map     each log event -> zero or more (key, 1) pairs
  shuffle group the pairs by key
  reduce  sum each group

It runs inside one Lambda here, but because the mapper is stateless and the
reducer is associative, the same functions could be split across many workers
(the way Hadoop or EMR would run them over HDFS/S3).
"""
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import timedelta
from typing import Any

from backend.config import ACKNOWLEDGED, CRITICAL, ERROR, OPEN, RESOLVED, SEVERITIES
from backend.util import iso, now, parse_iso

TIMELINE_MINUTES = 60

Pair = tuple[tuple, int]


def map_reduce(records: Iterable[Any], mapper: Callable[[Any], Iterable[Pair]],
               reducer: Callable[[tuple, list[int]], int]) -> dict[tuple, int]:
    shuffled: dict[tuple, list[int]] = defaultdict(list)
    for record in records:                      # map
        for key, value in mapper(record):
            shuffled[key].append(value)         # shuffle
    return {key: reducer(key, values) for key, values in shuffled.items()}  # reduce


def make_event_mapper(timeline_start: str) -> Callable[[dict[str, Any]], Iterable[Pair]]:
    def mapper(event: dict[str, Any]) -> Iterable[Pair]:
        level, service = event["level"], event["service"]
        yield ("level", level), 1
        yield ("service", service, level), 1
        if event["timestamp"] >= timeline_start:
            yield ("minute", event["timestamp"][:16], level), 1
        if level in (ERROR, CRITICAL) and event.get("error_code"):
            yield ("error_code", event["error_code"], service), 1
    return mapper


def sum_reducer(_key: tuple, values: list[int]) -> int:
    return sum(values)


def _minutes_between(start: str, end: str) -> float:
    return (parse_iso(end) - parse_iso(start)).total_seconds() / 60


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def build_overview(events: list[dict[str, Any]], incidents: list[dict[str, Any]],
                   window_hours: int = 24) -> dict[str, Any]:
    current = now()
    first_minute = current - timedelta(minutes=TIMELINE_MINUTES - 1)
    counts = map_reduce(events, make_event_mapper(iso(first_minute)[:16]), sum_reducer)

    by_level = {lvl: counts.get(("level", lvl), 0) for lvl in SEVERITIES}
    total = sum(by_level.values())

    timeline = []
    for i in range(TIMELINE_MINUTES):
        minute = iso(first_minute + timedelta(minutes=i))[:16]
        timeline.append({"minute": minute + ":00Z",
                         **{lvl: counts.get(("minute", minute, lvl), 0) for lvl in SEVERITIES}})

    active = [i for i in incidents if i["status"] in (OPEN, ACKNOWLEDGED)]
    services: dict[str, dict[str, Any]] = {}
    for key, value in counts.items():
        if key[0] == "service":
            row = services.setdefault(key[1], {"service": key[1], **{lvl: 0 for lvl in SEVERITIES}})
            row[key[2]] = value
    for inc in active:
        services.setdefault(inc["service"], {"service": inc["service"], **{lvl: 0 for lvl in SEVERITIES}})
    for name, row in services.items():
        mine = [i for i in active if i["service"] == name]
        row["total"] = sum(row[lvl] for lvl in SEVERITIES)
        row["active_incidents"] = len(mine)
        row["status"] = ("down" if any(i["severity"] == CRITICAL for i in mine)
                         else "degraded" if mine else "healthy")

    top_errors = sorted(
        ({"error_code": k[1], "service": k[2], "count": v} for k, v in counts.items() if k[0] == "error_code"),
        key=lambda r: r["count"], reverse=True,
    )[:6]

    mtta = [_minutes_between(i["created_at"], i["acknowledged_at"]) for i in incidents if i.get("acknowledged_at")]
    mttr = [_minutes_between(i["created_at"], i["resolved_at"])
            for i in incidents if i["status"] == RESOLVED and i.get("resolved_at")]

    return {
        "generated_at": iso(current),
        "window_hours": window_hours,
        "totals": {
            "events": total,
            "by_level": by_level,
            "error_rate": round(100 * (by_level[ERROR] + by_level[CRITICAL]) / total, 1) if total else 0.0,
        },
        "timeline": timeline,
        "services": sorted(services.values(), key=lambda r: (r["status"] == "healthy", r["service"])),
        "top_errors": top_errors,
        "incidents": {
            "open": sum(1 for i in incidents if i["status"] == OPEN),
            "acknowledged": sum(1 for i in incidents if i["status"] == ACKNOWLEDGED),
            "resolved": sum(1 for i in incidents if i["status"] == RESOLVED),
            "critical_active": sum(1 for i in active if i["severity"] == CRITICAL),
            "mtta_minutes": _mean(mtta),
            "mttr_minutes": _mean(mttr),
        },
    }
