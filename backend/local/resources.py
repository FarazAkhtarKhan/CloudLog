"""
Creates the CloudLog AWS resources inside an emulated account (moto).

The schemas mirror infrastructure/terraform/dynamodb.tf so the offline emulator
and the unit tests exercise exactly the same keys and indexes as production.
"""
from typing import Any


def _attrs(*names: str):
    return [{"AttributeName": n, "AttributeType": "S"} for n in names]


def _key(hash_key: str, range_key: str | None = None):
    schema = [{"AttributeName": hash_key, "KeyType": "HASH"}]
    if range_key:
        schema.append({"AttributeName": range_key, "KeyType": "RANGE"})
    return schema


def create_tables(dynamodb, events: str, incidents: str, runs: str) -> None:
    dynamodb.create_table(
        TableName=events, BillingMode="PAY_PER_REQUEST",
        KeySchema=_key("service", "sort_key"),
        AttributeDefinitions=_attrs("service", "sort_key", "feed_day"),
        GlobalSecondaryIndexes=[{
            "IndexName": "feed-index", "KeySchema": _key("feed_day", "sort_key"),
            "Projection": {"ProjectionType": "ALL"},
        }],
    )
    dynamodb.create_table(
        TableName=incidents, BillingMode="PAY_PER_REQUEST",
        KeySchema=_key("incident_id"),
        AttributeDefinitions=_attrs("incident_id", "status", "updated_at"),
        GlobalSecondaryIndexes=[{
            "IndexName": "status-updated_at-index", "KeySchema": _key("status", "updated_at"),
            "Projection": {"ProjectionType": "ALL"},
        }],
    )
    dynamodb.create_table(
        TableName=runs, BillingMode="PAY_PER_REQUEST",
        KeySchema=_key("stage", "run_key"),
        AttributeDefinitions=_attrs("stage", "run_key"),
    )


def provision(region: str, names: dict[str, str]) -> dict[str, Any]:
    """Create bucket, tables and topic; returns the topic ARN and boto3 handles."""
    import boto3

    s3 = boto3.client("s3", region_name=region)
    if region == "us-east-1":
        s3.create_bucket(Bucket=names["bucket"])
    else:
        s3.create_bucket(Bucket=names["bucket"], CreateBucketConfiguration={"LocationConstraint": region})
    dynamodb = boto3.resource("dynamodb", region_name=region)
    create_tables(dynamodb, names["events"], names["incidents"], names["runs"])
    sns = boto3.client("sns", region_name=region)
    topic_arn = sns.create_topic(Name=names["topic"])["TopicArn"]
    return {"s3": s3, "dynamodb": dynamodb, "sns": sns, "topic_arn": topic_arn}
