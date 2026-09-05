"""
Log Ingestion Reader.
Streams JSONL log lines line-by-line without loading entire files into memory,
attaches S3Context metadata, and delegates parsing to analyze_log_line().
"""
from pathlib import Path
from typing import Iterable, Union

from backend.analyzer.models import S3Context
from backend.analyzer.parser import analyze_log_line
from backend.ingestion.models import IngestionBatchResult


def ingest_jsonl_stream(
    stream: Iterable[str],
    bucket_name: str,
    object_key: str,
) -> IngestionBatchResult:
    """
    Process an iterable of log lines (e.g., an open file or string stream) line-by-line.

    Args:
        stream: Iterable yielding one raw log line at a time.
        bucket_name: S3 bucket identifier for provenance.
        object_key: S3 object key / path for provenance.

    Returns:
        IngestionBatchResult containing all valid events and invalid rejection records.
    """
    source_uri = f"s3://{bucket_name}/{object_key}"
    batch = IngestionBatchResult(source_s3_uri=source_uri)

    for line_number, raw_line in enumerate(stream, start=1):
        batch.total_lines += 1

        context = S3Context(
            bucket_name=bucket_name,
            object_key=object_key,
            line_number=line_number,
        )

        analysis = analyze_log_line(raw_line=raw_line, context=context)

        if analysis.is_valid and analysis.event is not None:
            batch.valid_events.append(analysis.event)
        else:
            batch.invalid_records.append(analysis)

    return batch


def ingest_jsonl_file(
    file_path: Union[str, Path],
    bucket_name: str,
    object_key: str,
) -> IngestionBatchResult:
    """
    Open and process a local JSONL log file line-by-line.
    Using Python's file iterator guarantees streaming without loading
    the full file into memory at once.

    Args:
        file_path: Local filesystem path to the JSONL file.
        bucket_name: Simulated or target S3 bucket name.
        object_key: Simulated or target S3 object key.

    Returns:
        IngestionBatchResult summarizing valid and invalid log records.
    """
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as file_stream:
        return ingest_jsonl_stream(
            stream=file_stream,
            bucket_name=bucket_name,
            object_key=object_key,
        )
