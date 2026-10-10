"""
Detection rules engine.

Takes the validated events of one log file and decides which of them describe a
problem worth an incident. Rules are evaluated in order; an event consumed by a
more specific rule (e.g. brute-force) is not counted again by a generic one.

Cross-file behaviour (grouping repeats, escalation after N occurrences, reopening
a resolved incident) lives in storage/incidents.py because it needs state.
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from backend.analyzer.models import LogEvent
from backend.config import (
    AUTH_FAILURE_CODES,
    BRUTE_FORCE_THRESHOLD,
    CRITICAL,
    ERROR,
    ESCALATION_THRESHOLD,
    SEVERITY_RANK,
    WARNING,
    WARNING_BURST_THRESHOLD,
)

RULES = [
    {
        "id": "critical-log",
        "name": "Critical log line",
        "severity": CRITICAL,
        "category": "Failure",
        "description": "Any CRITICAL line opens a critical incident and sends an SNS alert.",
    },
    {
        "id": "error-log",
        "name": "Error log line",
        "severity": ERROR,
        "category": "Failure",
        "description": "ERROR lines open an incident. Repeats of the same error join that incident.",
    },
    {
        "id": "brute-force",
        "name": "Brute-force login",
        "severity": CRITICAL,
        "category": "Security",
        "description": f"{BRUTE_FORCE_THRESHOLD} or more failed logins from one IP in a batch "
                       "open a critical security incident.",
    },
    {
        "id": "warning-burst",
        "name": "Warning burst",
        "severity": ERROR,
        "category": "Degradation",
        "description": f"The same warning {WARNING_BURST_THRESHOLD} or more times in a batch "
                       "is treated as an error.",
    },
    {
        "id": "escalation",
        "name": "Recurring error escalation",
        "severity": CRITICAL,
        "category": "Failure",
        "description": f"An error incident that reaches {ESCALATION_THRESHOLD} occurrences is "
                       "escalated to CRITICAL and alerted.",
    },
]


@dataclass
class Detection:
    """A problem found in one batch; becomes (or updates) one incident."""
    fingerprint: str
    rule_id: str
    severity: str
    category: str
    service: str
    title: str
    error_code: str | None
    first_seen: str
    last_seen: str
    count: int
    log_fingerprint: str = ""          # fingerprint shared by the member log lines
    source_ip: str | None = None
    event_ids: list[str] = field(default_factory=list)


def _summarise(events: list[LogEvent], **overrides) -> Detection:
    events = sorted(events, key=lambda e: e.timestamp)
    worst = max(events, key=lambda e: SEVERITY_RANK[e.level])
    fields = dict(
        fingerprint=worst.fingerprint,
        log_fingerprint=worst.fingerprint,
        rule_id="critical-log" if worst.level == CRITICAL else "error-log",
        severity=worst.level,
        category="Failure",
        service=worst.service,
        title=worst.message[:140],
        error_code=worst.error_code,
        first_seen=events[0].timestamp,
        last_seen=events[-1].timestamp,
        count=len(events),
        event_ids=[e.event_id for e in events[:20]],
    )
    fields.update(overrides)
    return Detection(**fields)


def detect(events: list[LogEvent]) -> list[Detection]:
    detections: list[Detection] = []
    consumed: set[str] = set()

    # Rule: brute-force (failed logins grouped by source IP)
    by_ip: dict[str, list[LogEvent]] = defaultdict(list)
    for e in events:
        if e.ip_address and e.error_code and e.error_code.upper() in AUTH_FAILURE_CODES:
            by_ip[e.ip_address].append(e)
    for ip, group in by_ip.items():
        if len(group) >= BRUTE_FORCE_THRESHOLD:
            detections.append(_summarise(
                group,
                fingerprint=hashlib.sha256(f"brute-force|{ip}".encode()).hexdigest()[:12],
                rule_id="brute-force",
                severity=CRITICAL,
                category="Security",
                title=f"Possible brute-force login attack from {ip}",
                source_ip=ip,
            ))
            consumed.update(e.event_id for e in group)

    remaining = [e for e in events if e.event_id not in consumed]

    # Rules: critical-log / error-log (grouped by fingerprint)
    failures: dict[str, list[LogEvent]] = defaultdict(list)
    warnings: dict[str, list[LogEvent]] = defaultdict(list)
    for e in remaining:
        if e.level in (ERROR, CRITICAL):
            failures[e.fingerprint].append(e)
        elif e.level == WARNING:
            warnings[e.fingerprint].append(e)
    detections.extend(_summarise(group) for group in failures.values())

    # Rule: warning-burst
    for group in warnings.values():
        if len(group) >= WARNING_BURST_THRESHOLD:
            detections.append(_summarise(
                group,
                rule_id="warning-burst",
                severity=ERROR,
                category="Degradation",
                title=f"Repeated warning: {group[0].message[:120]}",
            ))

    return detections
