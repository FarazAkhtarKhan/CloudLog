"""
Data models for the CloudLog Ingestion layer.
Defines the container for batch ingestion results.
"""
from dataclasses import dataclass, field
from typing import List

from backend.analyzer.models import AnalysisResult, LogEvent


@dataclass
class IngestionBatchResult:
    """
    Summary of processing a complete JSONL log file or stream.
    Separates valid LogEvent items ready for persistence from rejected records.
    """
    source_s3_uri: str
    total_lines: int = 0
    valid_events: List[LogEvent] = field(default_factory=list)
    invalid_records: List[AnalysisResult] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        """Count of successfully parsed and validated log events."""
        return len(self.valid_events)

    @property
    def invalid_count(self) -> int:
        """Count of rejected or malformed log lines."""
        return len(self.invalid_records)
