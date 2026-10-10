"""Small helpers shared across layers."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any


def now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    """UTC ISO-8601 with milliseconds and 'Z' - sorts correctly as a plain string."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso(now())


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ttl_epoch(days: int) -> int:
    """Epoch seconds `days` from now, for DynamoDB TTL attributes."""
    return int((now() + timedelta(days=days)).timestamp())


def plain(value: Any) -> Any:
    """Convert DynamoDB types (Decimal, set) into JSON-friendly Python values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value
