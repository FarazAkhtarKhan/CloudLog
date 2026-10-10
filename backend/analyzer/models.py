"""Data shapes produced by the analyzer."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogEvent:
    """One validated log line, ready to be stored in DynamoDB."""
    event_id: str
    service: str
    timestamp: str          # normalised: YYYY-MM-DDTHH:MM:SS.mmmZ
    level: str
    message: str            # PII-masked
    fingerprint: str        # groups "the same error" across lines and files
    source_s3_uri: str
    line_number: int
    error_code: str | None = None
    endpoint: str | None = None
    ip_address: str | None = None   # raw; masked when stored
    request_id: str | None = None
    pii_redacted: bool = False

    @property
    def sort_key(self) -> str:
        return f"{self.timestamp}#{self.event_id}"

    @property
    def feed_day(self) -> str:
        return self.timestamp[:10]

    def to_item(self, expires_at: int, ip_masked: str | None) -> dict[str, Any]:
        item: dict[str, Any] = {
            "service": self.service,
            "sort_key": self.sort_key,
            "feed_day": self.feed_day,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "fingerprint": self.fingerprint,
            "source_s3_uri": self.source_s3_uri,
            "line_number": self.line_number,
            "expires_at": expires_at,
        }
        optional = {
            "error_code": self.error_code,
            "endpoint": self.endpoint,
            "ip_address": ip_masked,
            "request_id": self.request_id,
        }
        item.update({k: v for k, v in optional.items() if v})
        if self.pii_redacted:
            item["pii_redacted"] = True
        return item


@dataclass
class Rejection:
    """A line that failed validation, with the reason."""
    line_number: int
    reason: str
    detail: str


@dataclass
class Batch:
    """Result of analysing one log file."""
    source_s3_uri: str
    events: list[LogEvent] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def total_lines(self) -> int:
        return len(self.events) + len(self.rejections)
