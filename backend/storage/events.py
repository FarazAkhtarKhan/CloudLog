"""
Events table (cloudlog_events).

  PK service | SK timestamp#event_id      -> one service's logs, newest first
  GSI feed-index: PK feed_day | SK sort_key -> all services' logs for a day, newest first
  TTL expires_at                            -> logs age out after EVENT_TTL_DAYS
"""
from datetime import timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from backend.analyzer.models import LogEvent
from backend.analyzer.privacy import mask_ip
from backend.config import EVENT_TTL_DAYS, events_table
from backend.storage.dynamo import purge, query_pages, table
from backend.util import iso, now, ttl_epoch

FEED_INDEX = "feed-index"


class EventsStore:
    def __init__(self, table_name: str | None = None, dynamodb: Any | None = None):
        self.table = table(table_name or events_table(), dynamodb)

    def save(self, events: list[LogEvent]) -> int:
        expires_at = ttl_epoch(EVENT_TTL_DAYS)
        with self.table.batch_writer(overwrite_by_pkeys=["service", "sort_key"]) as batch:
            for e in events:
                ip = mask_ip(e.ip_address) if e.ip_address else None
                batch.put_item(Item=e.to_item(expires_at=expires_at, ip_masked=ip))
        return len(events)

    def recent(
        self,
        limit: int = 50,
        level: str | None = None,
        service: str | None = None,
        search: str | None = None,
        fingerprint: str | None = None,
        days: int = EVENT_TTL_DAYS,
    ) -> list[dict[str, Any]]:
        """Newest-first log feed with optional filters."""
        conditions = []
        if level:
            conditions.append(Attr("level").eq(level))
        if fingerprint:
            conditions.append(Attr("fingerprint").eq(fingerprint))
        if search:
            conditions.append(Attr("message").contains(search) | Attr("error_code").contains(search.upper()))
        extra: dict[str, Any] = {"ScanIndexForward": False, "Limit": max(limit, 50)}
        if conditions:
            expr = conditions[0]
            for c in conditions[1:]:
                expr = expr & c
            extra["FilterExpression"] = expr

        if service:
            return query_pages(self.table, limit, KeyConditionExpression=Key("service").eq(service), **extra)

        items: list[dict[str, Any]] = []
        today = now()
        for offset in range(days):
            day = iso(today - timedelta(days=offset))[:10]
            items += query_pages(
                self.table, limit - len(items), IndexName=FEED_INDEX,
                KeyConditionExpression=Key("feed_day").eq(day), **extra,
            )
            if len(items) >= limit:
                break
        return items

    def since(self, hours: int = 24, cap: int = 5000) -> list[dict[str, Any]]:
        """Every event in the last `hours` (input for the MapReduce analytics)."""
        cutoff = iso(now() - timedelta(hours=hours))
        days = sorted({cutoff[:10], iso(now())[:10]}, reverse=True)
        items: list[dict[str, Any]] = []
        for day in days:
            items += query_pages(
                self.table, cap - len(items), max_pages=50, IndexName=FEED_INDEX,
                KeyConditionExpression=Key("feed_day").eq(day) & Key("sort_key").gte(cutoff),
                ScanIndexForward=False,
            )
        return items

    def purge(self) -> int:
        return purge(self.table, ["service", "sort_key"])
