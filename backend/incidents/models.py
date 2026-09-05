"""
Data models and generators for CloudLog Incidents.
Defines Incident dataclass, status constants, and event-to-incident transformation.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.analyzer.models import LogEvent
from backend.common.config import SEVERITY_CRITICAL, SEVERITY_ERROR

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"
VALID_INCIDENT_STATUSES = {STATUS_OPEN, STATUS_RESOLVED}

INCIDENT_INDEX_NAME = "status-created_at-index"


def generate_incident_id(event_id: str) -> str:
    """
    Derive deterministic incident ID from the triggering LogEvent event_id.
    Formula: 'inc_' + event_id[4:]
    Example: evt_8f14c2b9a70e31d4 -> inc_8f14c2b9a70e31d4
    """
    hex_part = event_id[4:] if event_id.startswith("evt_") else event_id
    return f"inc_{hex_part}"


@dataclass
class Incident:
    """Represents an actionable operational anomaly in CloudLog."""
    incident_id: str
    service: str
    severity: str  # ERROR or CRITICAL
    status: str    # OPEN or RESOLVED
    message: str
    source_event_id: str
    source_s3_uri: str
    created_at: str
    error_code: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item dictionary for cloudlog_incidents table."""
        item: Dict[str, Any] = {
            "incident_id": self.incident_id,
            "service": self.service,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "source_event_id": self.source_event_id,
            "source_s3_uri": self.source_s3_uri,
            "created_at": self.created_at,
        }
        if self.error_code:
            item["error_code"] = self.error_code
        if self.resolved_at:
            item["resolved_at"] = self.resolved_at
        if self.resolved_by:
            item["resolved_by"] = self.resolved_by
        return item


def create_incident_from_event(
    event: LogEvent,
    created_at: Optional[str] = None,
) -> Optional[Incident]:
    """
    Generate an Incident from a LogEvent if its severity warrants one (ERROR or CRITICAL).
    Returns None for INFO and WARNING events.

    Args:
        event: Validated LogEvent.
        created_at: Optional creation timestamp (defaults to current UTC ISO 8601).

    Returns:
        Incident if event is ERROR or CRITICAL, None otherwise.
    """
    if event.level not in {SEVERITY_ERROR, SEVERITY_CRITICAL}:
        return None

    incident_id = generate_incident_id(event.event_id)
    timestamp = created_at or datetime.now(timezone.utc).isoformat()

    return Incident(
        incident_id=incident_id,
        service=event.service,
        severity=event.level,
        status=STATUS_OPEN,
        message=event.message,
        source_event_id=event.event_id,
        source_s3_uri=event.source_s3_uri,
        created_at=timestamp,
        error_code=event.error_code,
        resolved_at=None,
    )
