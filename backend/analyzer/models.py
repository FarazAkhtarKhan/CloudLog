"""
Data models for the CloudLog Analyzer.
Defines immutable context, structured log events, and analysis results.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class S3Context:
    """Metadata describing the origin of a log record within Amazon S3."""
    bucket_name: str
    object_key: str
    line_number: int

    @property
    def source_s3_uri(self) -> str:
        """Formatted S3 URI for provenance tracking."""
        return f"s3://{self.bucket_name}/{self.object_key}"


@dataclass
class LogEvent:
    """A fully validated, classified, and enriched CloudLog event."""
    event_id: str
    service: str
    timestamp: str
    sort_key: str  # timestamp#event_id
    level: str
    message: str
    source_s3_uri: str
    line_number: int
    processed_at: str
    is_incident: bool
    requires_alert: bool
    error_code: Optional[str] = None
    endpoint: Optional[str] = None
    ip_address: Optional[str] = None

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """
        Convert to DynamoDB item structure adhering to the finalized schema contract.
        Omitted optional fields are not stored as nulls to keep records lean.
        """
        item: Dict[str, Any] = {
            "service": self.service,
            "sort_key": self.sort_key,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "level": self.level,
            "message": self.message,
            "source_s3_uri": self.source_s3_uri,
            "line_number": self.line_number,
            "processed_at": self.processed_at,
        }
        if self.error_code:
            item["error_code"] = self.error_code
        if self.endpoint:
            item["endpoint"] = self.endpoint
        if self.ip_address:
            item["ip_address"] = self.ip_address
        return item


@dataclass
class AnalysisResult:
    """
    Standardized return object for the analyzer.
    Indicates success (with LogEvent) or rejection (with error classification).
    """
    is_valid: bool
    event: Optional[LogEvent] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    line_number: Optional[int] = None
    source_s3_uri: Optional[str] = None
