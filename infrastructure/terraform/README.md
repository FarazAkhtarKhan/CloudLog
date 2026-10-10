# CloudLog infrastructure (Terraform)

Every AWS resource CloudLog uses is defined here. Deployment steps are in the [root README](../../README.md#deploy-to-aws).

| File | Resources |
| --- | --- |
| `s3.tf` | Raw log bucket: encryption, public access block, `.jsonl` → Lambda notification, lifecycle tiering |
| `lambda.tf` | Deployment package, processor Lambda, async retries with SQS dead-letter destination |
| `api_lambda.tf` | API Lambda and its least-privilege role |
| `iam.tf` | Processor's least-privilege role |
| `dynamodb.tf` | `cloudlog_events` (+ `feed-index`, TTL), `cloudlog_incidents` (+ status GSI, PITR), `cloudlog_pipeline_runs` (TTL) |
| `api_gateway.tf` | HTTP API, Cognito JWT authorizer, routes, throttling |
| `cognito.tf` | User pool, web client, Admin / Analyst / Viewer groups, demo users |
| `sns.tf` | Critical alert topic and optional email subscription (`-var alert_email=...`) |
| `sqs.tf` | Processor dead-letter queue |
| `cloudwatch.tf` | Log groups with retention, alarms on processor errors and DLQ depth |
| `hosting.tf` | Private dashboard bucket + CloudFront distribution with Origin Access Control |

Useful outputs after `apply`:

```bash
terraform output dashboard_url
terraform output -raw frontend_env      # paste into frontend/.env.local for local development
```

`enable_dashboard_hosting=false` skips CloudFront if you only want the backend.
