"""
Pipeline-runs table (cloudlog_pipeline_runs): one record per processed S3 file.

  PK stage ("processor") | SK started_at#run_id -> newest runs first with one Query
  TTL expires_at                                -> run history ages out after RUN_TTL_DAYS

The dashboard uses these records to trace a log file through S3 -> Lambda -> DynamoDB -> SNS.
"""
from typing import Any

from boto3.dynamodb.conditions import Key

from backend.config import PIPELINE_STAGE, RUN_TTL_DAYS, runs_table
from backend.storage.dynamo import purge, query_pages, table
from backend.util import ttl_epoch


class RunsStore:
    def __init__(self, table_name: str | None = None, dynamodb: Any | None = None):
        self.table = table(table_name or runs_table(), dynamodb)

    def save(self, run: dict[str, Any]) -> None:
        item = dict(run)
        item["stage"] = PIPELINE_STAGE
        item["run_key"] = f"{run['started_at']}#{run['run_id']}"
        item["expires_at"] = ttl_epoch(RUN_TTL_DAYS)
        self.table.put_item(Item=item)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return query_pages(
            self.table, limit, Limit=limit, ScanIndexForward=False,
            KeyConditionExpression=Key("stage").eq(PIPELINE_STAGE),
        )

    def purge(self) -> int:
        return purge(self.table, ["stage", "run_key"])
