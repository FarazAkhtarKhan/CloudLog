"""
DynamoDB repository for the CloudLog incidents table (cloudlog_incidents).
Provides persistence, GSI-based queries for open incidents, and lifecycle updates using boto3.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.common.config import get_aws_region, get_incidents_table_name
from backend.incidents.models import (
    INCIDENT_INDEX_NAME,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Incident,
)


def _item_to_incident(item: Dict[str, Any]) -> Incident:
    """Reconstruct an Incident dataclass from a DynamoDB item dictionary."""
    return Incident(
        incident_id=str(item["incident_id"]),
        service=str(item["service"]),
        severity=str(item["severity"]),
        status=str(item["status"]),
        message=str(item.get("message", "")),
        source_event_id=str(item["source_event_id"]),
        source_s3_uri=str(item.get("source_s3_uri", "")),
        created_at=str(item["created_at"]),
        error_code=item.get("error_code"),
        resolved_at=item.get("resolved_at"),
        resolved_by=item.get("resolved_by"),
    )


class IncidentsRepository:
    """
    Data Access Layer for the 'cloudlog_incidents' DynamoDB table.
    Encapsulates primary key lookups, GSI queries, and lifecycle resolution.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        dynamodb_resource: Optional[Any] = None,
    ) -> None:
        """
        Initialize the IncidentsRepository.

        Args:
            table_name: DynamoDB table name (defaults to INCIDENTS_TABLE_NAME config).
            dynamodb_resource: Optional pre-configured boto3 DynamoDB resource (useful for tests/mocking).
        """
        self.table_name = table_name or get_incidents_table_name()
        self.region_name = get_aws_region()

        if dynamodb_resource is not None:
            self._dynamodb = dynamodb_resource
        else:
            self._dynamodb = boto3.resource("dynamodb", region_name=self.region_name)

        self._table = self._dynamodb.Table(self.table_name)

    def save_incident(self, incident: Incident) -> None:
        """
        Save or overwrite an Incident record in DynamoDB.
        Idempotent because incident_id is derived deterministically from the source event.
        """
        item = incident.to_dynamodb_item()
        self._table.put_item(Item=item)

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """
        Retrieve an incident by primary key (incident_id).

        Args:
            incident_id: Primary key (e.g. 'inc_8f14c2b9a70e31d4').

        Returns:
            Incident if found, None otherwise.
        """
        response = self._table.get_item(Key={"incident_id": incident_id})
        item = response.get("Item")
        if not item:
            return None
        return _item_to_incident(item)

    def get_open_incidents(
        self,
        limit: int = 50,
        scan_forward: bool = False,
    ) -> List[Incident]:
        """
        Query all active (OPEN) incidents using the GSI (status-created_at-index).

        Args:
            limit: Maximum incidents to retrieve (default 50).
            scan_forward: True for chronological, False for reverse-chronological (newest first).

        Returns:
            List of Incident objects with status='OPEN'.
        """
        response = self._table.query(
            IndexName=INCIDENT_INDEX_NAME,
            KeyConditionExpression=Key("status").eq(STATUS_OPEN),
            Limit=limit,
            ScanIndexForward=scan_forward,
        )
        items = response.get("Items", [])
        return [_item_to_incident(item) for item in items]

    def resolve_incident(
        self,
        incident_id: str,
        resolved_at: Optional[str] = None,
        resolved_by: Optional[str] = None,
    ) -> Optional[Incident]:
        """
        Transition an incident from OPEN to RESOLVED and set its resolution timestamp.
        Uses a conditional update to ensure non-existent IDs are not accidentally inserted.

        Args:
            incident_id: Primary key of incident to resolve.
            resolved_at: Optional ISO 8601 resolution timestamp (defaults to current UTC).
            resolved_by: Optional identifier of the user who resolved the incident.

        Returns:
            Updated Incident object if resolved, None if incident_id does not exist.
        """
        resolution_time = resolved_at or datetime.now(timezone.utc).isoformat()

        update_expr = "SET #st = :status, resolved_at = :resolved_at"
        expr_vals: Dict[str, Any] = {
            ":status": STATUS_RESOLVED,
            ":resolved_at": resolution_time,
        }
        if resolved_by:
            update_expr += ", resolved_by = :resolved_by"
            expr_vals[":resolved_by"] = resolved_by

        try:
            response = self._table.update_item(
                Key={"incident_id": incident_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues=expr_vals,
                ConditionExpression="attribute_exists(incident_id)",
                ReturnValues="ALL_NEW",
            )
            return _item_to_incident(response["Attributes"])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise exc

    def get_all_incidents(self, limit: int = 50) -> List[Incident]:
        """
        Retrieve all incidents (both OPEN and RESOLVED) sorted newest first.

        Args:
            limit: Maximum items to return (default 50).

        Returns:
            List of Incident objects ordered by created_at descending.
        """
        response = self._table.scan(Limit=limit * 2)
        items = response.get("Items", [])
        incidents = [_item_to_incident(item) for item in items]
        incidents.sort(key=lambda x: x.created_at, reverse=True)
        return incidents[:limit]

