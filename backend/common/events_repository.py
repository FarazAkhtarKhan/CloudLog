"""
DynamoDB repository for the CloudLog events table (cloudlog_events).
Provides persistence and query interfaces for LogEvent objects using boto3.
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

from backend.analyzer.models import LogEvent
from backend.common.config import (
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    get_aws_region,
    get_events_table_name,
)


def _item_to_log_event(item: Dict[str, Any]) -> LogEvent:
    """
    Reconstruct a LogEvent dataclass instance from a DynamoDB item dictionary.
    Handles DynamoDB Decimal type conversion for numeric fields like line_number.
    """
    line_number_raw = item.get("line_number", 0)
    line_number = int(line_number_raw) if isinstance(line_number_raw, (int, float, Decimal)) else 0

    level = str(item.get("level", "INFO"))
    is_incident = level in {SEVERITY_ERROR, SEVERITY_CRITICAL}
    requires_alert = level == SEVERITY_CRITICAL

    return LogEvent(
        event_id=str(item["event_id"]),
        service=str(item["service"]),
        timestamp=str(item["timestamp"]),
        sort_key=str(item["sort_key"]),
        level=level,
        message=str(item.get("message", "")),
        source_s3_uri=str(item.get("source_s3_uri", "")),
        line_number=line_number,
        processed_at=str(item.get("processed_at", "")),
        is_incident=is_incident,
        requires_alert=requires_alert,
        error_code=item.get("error_code"),
        endpoint=item.get("endpoint"),
        ip_address=item.get("ip_address"),
    )


class EventsRepository:
    """
    Data Access Layer (Repository Pattern) for the 'cloudlog_events' DynamoDB table.
    Encapsulates all DynamoDB SDK operations and item serialization.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        dynamodb_resource: Optional[Any] = None,
    ) -> None:
        """
        Initialize the repository.

        Args:
            table_name: DynamoDB table name (defaults to EVENTS_TABLE_NAME config).
            dynamodb_resource: Optional pre-configured boto3 DynamoDB resource (useful for tests/mocking).
        """
        self.table_name = table_name or get_events_table_name()
        self.region_name = get_aws_region()

        if dynamodb_resource is not None:
            self._dynamodb = dynamodb_resource
        else:
            self._dynamodb = boto3.resource("dynamodb", region_name=self.region_name)

        self._table = self._dynamodb.Table(self.table_name)

    def save_event(self, event: LogEvent) -> None:
        """
        Save or overwrite a single LogEvent in DynamoDB.
        Reuses LogEvent.to_dynamodb_item() to produce the DynamoDB item dictionary.
        Because sort_key contains a deterministic event_id, re-saving the same event
        is an idempotent overwrite that prevents duplicate logical records.
        """
        item = event.to_dynamodb_item()
        self._table.put_item(Item=item)

    def save_events(self, events: List[LogEvent]) -> int:
        """
        Batch save a list of LogEvent objects using DynamoDB batch_writer.
        Returns the count of events submitted.
        """
        if not events:
            return 0

        with self._table.batch_writer() as batch:
            for event in events:
                batch.put_item(Item=event.to_dynamodb_item())

        return len(events)

    def get_event(self, service: str, sort_key: str) -> Optional[LogEvent]:
        """
        Retrieve a single LogEvent by primary key (service + sort_key).

        Args:
            service: Partition Key (service name, e.g. 'payment-service').
            sort_key: Sort Key (format: 'timestamp#event_id').

        Returns:
            LogEvent if found, None otherwise.
        """
        response = self._table.get_item(
            Key={
                "service": service,
                "sort_key": sort_key,
            }
        )
        item = response.get("Item")
        if not item:
            return None
        return _item_to_log_event(item)

    def get_events_by_service(
        self,
        service: str,
        limit: int = 50,
        scan_forward: bool = False,
    ) -> List[LogEvent]:
        """
        Query all events for a given service ordered by sort_key.

        Args:
            service: Partition key value to query.
            limit: Maximum items to return (default 50).
            scan_forward: True for chronological (ascending), False for reverse-chronological (descending).

        Returns:
            List of LogEvent objects matching the query.
        """
        response = self._table.query(
            KeyConditionExpression=Key("service").eq(service),
            Limit=limit,
            ScanIndexForward=scan_forward,
        )
        items = response.get("Items", [])
        return [_item_to_log_event(item) for item in items]

    def scan_recent_events(
        self,
        limit: int = 50,
        level: Optional[str] = None,
        service: Optional[str] = None,
    ) -> List[LogEvent]:
        """
        Retrieve recent log events across services or for a specific service,
        optionally filtered by severity level. Results are sorted newest first.

        Args:
            limit: Maximum items to return (default 50).
            level: Optional severity filter (e.g. 'CRITICAL', 'ERROR').
            service: Optional microservice filter.

        Returns:
            List of LogEvent objects sorted by timestamp descending.
        """
        if service:
            events = self.get_events_by_service(service=service, limit=limit, scan_forward=False)
            if level:
                events = [e for e in events if e.level == level]
            return events[:limit]

        # Scan across all services with optional level filter
        scan_kwargs: Dict[str, Any] = {"Limit": min(limit * 3, 200)}
        if level:
            scan_kwargs["FilterExpression"] = Attr("level").eq(level)

        response = self._table.scan(**scan_kwargs)
        items = response.get("Items", [])
        events = [_item_to_log_event(item) for item in items]
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Aggregate telemetry statistics across all events for the dashboard.

        Returns:
            Dictionary containing total_events, severity counts, and critical events by service.
        """
        response = self._table.scan()
        items = response.get("Items", [])

        total_events = len(items)
        severity_counts = {
            "INFO": 0,
            "WARNING": 0,
            "ERROR": 0,
            "CRITICAL": 0,
        }
        critical_by_service: Dict[str, int] = {}
        services_set = set()

        for item in items:
            level = item.get("level", "INFO")
            service = item.get("service", "unknown")
            services_set.add(service)

            if level in severity_counts:
                severity_counts[level] += 1
            else:
                severity_counts[level] = 1

            if level == SEVERITY_CRITICAL:
                critical_by_service[service] = critical_by_service.get(service, 0) + 1

        return {
            "total_events": total_events,
            "severity_counts": severity_counts,
            "error_count": severity_counts.get("ERROR", 0),
            "critical_count": severity_counts.get("CRITICAL", 0),
            "critical_by_service": critical_by_service,
            "total_services": len(services_set),
        }

    def get_services(self) -> List[str]:
        """
        Retrieve a sorted list of unique microservices that have generated telemetry.
        """
        response = self._table.scan(ProjectionExpression="#svc", ExpressionAttributeNames={"#svc": "service"})
        items = response.get("Items", [])
        services = sorted({item["service"] for item in items if "service" in item})
        return services

