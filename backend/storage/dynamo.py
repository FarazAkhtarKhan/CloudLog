"""Shared DynamoDB plumbing: table handles, paginated queries, purge."""
from collections.abc import Iterator
from typing import Any

import boto3

from backend.config import aws_region


def table(name: str, dynamodb: Any | None = None):
    resource = dynamodb or boto3.resource("dynamodb", region_name=aws_region())
    return resource.Table(name)


def query_pages(tbl, want: int, max_pages: int = 10, **kwargs) -> list[dict[str, Any]]:
    """
    Run a Query, following LastEvaluatedKey until `want` items are collected.
    Needed because DynamoDB applies Limit *before* FilterExpression.
    """
    items: list[dict[str, Any]] = []
    for _ in range(max_pages):
        response = tbl.query(**kwargs)
        items.extend(response.get("Items", []))
        if len(items) >= want or "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return items[:want]


def scan_all(tbl, **kwargs) -> Iterator[dict[str, Any]]:
    while True:
        response = tbl.scan(**kwargs)
        yield from response.get("Items", [])
        if "LastEvaluatedKey" not in response:
            return
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def purge(tbl, key_names: list[str]) -> int:
    """Delete every item (used by the admin 'reset demo data' action)."""
    names = {f"#k{i}": k for i, k in enumerate(key_names)}
    deleted = 0
    with tbl.batch_writer() as batch:
        for item in scan_all(tbl, ProjectionExpression=", ".join(names), ExpressionAttributeNames=names):
            batch.delete_item(Key={k: item[k] for k in key_names})
            deleted += 1
    return deleted
