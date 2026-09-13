#!/usr/bin/env bash
# Helper script to send a batch of sample logs to Amazon S3
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-terraform}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"

COUNT="${1:-25}"

echo "======================================================"
echo " Uploading $COUNT sample logs to Amazon S3..."
echo "======================================================"

"$DIR/.venv/bin/python" "$DIR/scripts/generate_sample_logs.py" --count "$COUNT"
