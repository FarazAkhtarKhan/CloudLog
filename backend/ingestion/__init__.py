"""
Log ingestion module for handling log files, streams, and S3 event extraction.
"""
from backend.ingestion.handler import lambda_handler, process_s3_event
from backend.ingestion.models import IngestionBatchResult
from backend.ingestion.reader import ingest_jsonl_file, ingest_jsonl_stream

__all__ = [
    "IngestionBatchResult",
    "ingest_jsonl_file",
    "ingest_jsonl_stream",
    "lambda_handler",
    "process_s3_event",
]
