#!/usr/bin/env bash
# Build the dashboard against the deployed API and publish it to S3 + CloudFront.
#   ./scripts/deploy_dashboard.sh        (uses your normal AWS credentials / AWS_PROFILE)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="$ROOT/infrastructure/terraform"
out() { terraform -chdir="$TF" output -raw "$1"; }

BUCKET="$(out dashboard_bucket)"
DISTRIBUTION="$(out dashboard_distribution_id)"

echo "Building dashboard for $(out api_gateway_endpoint)"
terraform -chdir="$TF" output -raw frontend_env > "$ROOT/frontend/.env.production.local"
npm --prefix "$ROOT/frontend" ci --silent
npm --prefix "$ROOT/frontend" run build

echo "Uploading to s3://$BUCKET"
aws s3 sync "$ROOT/frontend/dist" "s3://$BUCKET" --delete \
  --cache-control "public,max-age=31536000,immutable" --exclude index.html
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache"

aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths "/index.html" >/dev/null
echo "Done: $(out dashboard_url)"
