#!/usr/bin/env bash
# Helper script to trigger a CRITICAL or custom incident in CloudLog
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-terraform}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"

LEVEL="${1:-CRITICAL}"
SERVICE="${2:-database-cluster}"
MESSAGE="${3:-CRITICAL: Database connection pool exhausted. Deadlock detected.}"
ERROR_CODE="${4:-CRIT_DEADLOCK_DETECTED}"

echo "======================================================"
echo " Triggering incident in CloudLog..."
echo " Level:       $LEVEL"
echo " Service:     $SERVICE"
echo " Message:     $MESSAGE"
echo " Error Code:  $ERROR_CODE"
echo "======================================================"

"$DIR/.venv/bin/python" "$DIR/scripts/generate_sample_logs.py" \
  --level "$LEVEL" \
  --service "$SERVICE" \
  --message "$MESSAGE" \
  --error-code "$ERROR_CODE"
