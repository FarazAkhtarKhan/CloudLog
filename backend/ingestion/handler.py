"""
AWS Lambda Ingestion Handler.
Acts as the serverless adapter connecting S3 ObjectCreated event notifications
to the local streaming ingestion reader and DynamoDB EventsRepository.
"""
import json
import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

from backend.common.config import get_aws_region
from backend.common.events_repository import EventsRepository
from backend.incidents.models import create_incident_from_event
from backend.incidents.publisher import SNSPublisher
from backend.incidents.repository import IncidentsRepository
from backend.ingestion.models import IngestionBatchResult
from backend.ingestion.reader import ingest_jsonl_stream

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _iter_s3_lines(body: Any) -> Iterable[str]:
    """
    Stream decoded UTF-8 text lines from an S3 StreamingBody.
    Yields one line at a time to keep Lambda memory consumption minimal.
    Non-decodable bytes are yielded as placeholder strings so the analyzer
    can catch and flag the error at the exact line number without aborting.
    """
    for raw_line in body.iter_lines():
        if raw_line is None:
            continue
        try:
            line_str = raw_line.decode("utf-8")
            yield line_str
        except UnicodeDecodeError as exc:
            logger.warning("Unicode decoding failed on log line: %s", exc)
            yield '{"error": "CORRUPTED_NON_UTF8_BYTES"}'


def process_s3_event(
    event: Dict[str, Any],
    s3_client: Optional[Any] = None,
    repository: Optional[EventsRepository] = None,
    incidents_repository: Optional[IncidentsRepository] = None,
    sns_publisher: Optional[SNSPublisher] = None,
) -> Dict[str, Any]:
    """
    Process an S3 ObjectCreated event notification.
    Extracts bucket and object key, streams the file, runs ingestion/analysis,
    persists valid events into DynamoDB, generates incidents for ERROR/CRITICAL,
    and publishes alerts to SNS for CRITICAL incidents.

    Args:
        event: S3 Event notification payload.
        s3_client: Optional boto3 S3 client (injected for testing/mocking).
        repository: Optional EventsRepository instance (injected for testing/mocking).
        incidents_repository: Optional IncidentsRepository instance (injected for testing/mocking).
        sns_publisher: Optional SNSPublisher instance (injected for testing/mocking).

    Returns:
        Dictionary conforming to standard Lambda proxy / execution response.
    """
    # 1. Validate top-level S3 event structure
    if not isinstance(event, dict) or "Records" not in event or not event["Records"]:
        logger.error("Event payload missing or contains empty 'Records' list: %s", event)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing or empty 'Records' in event payload"}),
        }

    # Initialize clients if not injected
    region = get_aws_region()
    client = s3_client or boto3.client("s3", region_name=region)
    repo = repository or EventsRepository()
    inc_repo = incidents_repository or IncidentsRepository()
    publisher = sns_publisher or SNSPublisher()

    processed_summaries: List[Dict[str, Any]] = []
    total_lines = 0
    total_valid = 0
    total_invalid = 0
    total_incidents = 0
    total_alerts = 0

    # 2. Iterate through all S3 records in the event
    for record in event["Records"]:
        s3_meta = record.get("s3")
        if not s3_meta:
            logger.warning("Skipping non-S3 record in event: %s", record)
            continue

        bucket_name = s3_meta.get("bucket", {}).get("name")
        raw_key = s3_meta.get("object", {}).get("key")

        if not bucket_name or not raw_key:
            logger.error("Malformed S3 record missing bucket name or key: %s", s3_meta)
            continue

        # Crucial: S3 URL-encodes object keys (e.g. '+' for spaces, percent-encoding)
        object_key = unquote_plus(raw_key)

        logger.info("Starting processing for s3://%s/%s", bucket_name, object_key)

        # 3. Retrieve object stream from S3
        try:
            response = client.get_object(Bucket=bucket_name, Key=object_key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error("Failed to retrieve S3 object s3://%s/%s: %s", bucket_name, object_key, exc)
            status_code = 404 if error_code == "NoSuchKey" else 500
            return {
                "statusCode": status_code,
                "body": json.dumps({
                    "error": f"S3 retrieval failure: {error_code}",
                    "bucket": bucket_name,
                    "key": object_key,
                }),
            }

        # 4. Stream lines through the local ingestion reader and analyzer
        body_stream = _iter_s3_lines(response["Body"])
        batch_result: IngestionBatchResult = ingest_jsonl_stream(
            stream=body_stream,
            bucket_name=bucket_name,
            object_key=object_key,
        )

        # 5. Log details for any rejected lines without failing the entire file
        for invalid in batch_result.invalid_records:
            logger.warning(
                "Rejected log line %s in %s: %s - %s",
                invalid.line_number,
                invalid.source_s3_uri,
                invalid.error_type,
                invalid.error_message,
            )

        # 6. Save all valid events to DynamoDB
        file_incidents = 0
        file_alerts = 0
        if batch_result.valid_events:
            try:
                repo.save_events(batch_result.valid_events)
                logger.info(
                    "Persisted %d events to DynamoDB for %s",
                    batch_result.valid_count,
                    batch_result.source_s3_uri,
                )
            except ClientError as exc:
                logger.error("DynamoDB persistence failure for %s: %s", batch_result.source_s3_uri, exc)
                raise exc

            # 7. Generate incidents for ERROR / CRITICAL events & alert via SNS for CRITICAL
            for valid_event in batch_result.valid_events:
                incident = create_incident_from_event(valid_event)
                if incident is not None:
                    try:
                        inc_repo.save_incident(incident)
                        file_incidents += 1
                        logger.info(
                            "Created incident %s (severity: %s) for event %s",
                            incident.incident_id,
                            incident.severity,
                            valid_event.event_id,
                        )
                    except ClientError as exc:
                        logger.error(
                            "Failed to persist incident %s for event %s: %s",
                            incident.incident_id,
                            valid_event.event_id,
                            exc,
                        )
                        raise exc

                    # Trigger SNS alert only for CRITICAL incidents
                    if incident.severity == "CRITICAL":
                        try:
                            pub_result = publisher.publish_critical_alert(incident)
                            if pub_result.published:
                                file_alerts += 1
                                logger.info(
                                    "Published critical alert for incident %s to SNS topic (MessageId: %s)",
                                    incident.incident_id,
                                    pub_result.message_id,
                                )
                        except Exception as exc:
                            # Alert delivery failure should not abort the log processing pipeline
                            logger.error(
                                "Failed to publish SNS alert for critical incident %s: %s",
                                incident.incident_id,
                                exc,
                            )

        total_lines += batch_result.total_lines
        total_valid += batch_result.valid_count
        total_invalid += batch_result.invalid_count
        total_incidents += file_incidents
        total_alerts += file_alerts

        processed_summaries.append({
            "source_s3_uri": batch_result.source_s3_uri,
            "total_lines": batch_result.total_lines,
            "valid_count": batch_result.valid_count,
            "invalid_count": batch_result.invalid_count,
            "incidents_count": file_incidents,
            "alerts_count": file_alerts,
        })

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "S3 log processing complete",
            "processed_files": len(processed_summaries),
            "total_lines": total_lines,
            "valid_count": total_valid,
            "invalid_count": total_invalid,
            "incidents_count": total_incidents,
            "alerts_count": total_alerts,
            "files": processed_summaries,
        }),
    }


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Standard AWS Lambda execution entry point.
    """
    return process_s3_event(event=event)
