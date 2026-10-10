#!/usr/bin/env python3
"""
Upload a log file straight to the S3 bucket, the way a real service would.
This bypasses the dashboard and API entirely: the S3 event alone drives the pipeline.

    # a built-in scenario (see backend/simulator/scenarios.py)
    python scripts/upload_logs.py --scenario db-outage

    # your own JSON Lines file
    python scripts/upload_logs.py --file my-logs.jsonl

The bucket and region are read from `terraform output` unless given as options.
"""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import boto3  # noqa: E402

from backend.simulator.scenarios import SCENARIOS, render  # noqa: E402


def terraform_output(name: str) -> str:
    out = subprocess.run(["terraform", "output", "-raw", name], cwd=ROOT / "infrastructure" / "terraform",
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", choices=sorted(SCENARIOS))
    source.add_argument("--file", type=Path, help="a .jsonl file to upload")
    parser.add_argument("--bucket", help="defaults to the Terraform output s3_log_bucket_name")
    parser.add_argument("--region", help="defaults to the Terraform output aws_region")
    args = parser.parse_args()

    bucket = args.bucket or terraform_output("s3_log_bucket_name")
    if args.scenario:
        body, name = "\n".join(render(args.scenario)) + "\n", args.scenario
    else:
        body, name = args.file.read_text(encoding="utf-8"), args.file.stem
    key = f"raw-logs/uploads/{time.strftime('%Y/%m/%d')}/{name}-{uuid.uuid4().hex[:8]}.jsonl"

    region = args.region or terraform_output("aws_region")
    boto3.client("s3", region_name=region).put_object(
        Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/x-ndjson",
        Metadata={"scenario": name, "triggered-by": "cli"},
    )
    print(json.dumps({"uploaded": f"s3://{bucket}/{key}", "lines": body.count("\n")}, indent=2))
    print("The processor Lambda runs within a second or two; watch the Pipeline page.")


if __name__ == "__main__":
    main()
