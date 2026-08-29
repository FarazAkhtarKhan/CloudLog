# Infrastructure as Code (Terraform)

This directory will contain Terraform configurations for provisioning AWS serverless resources:
- `s3.tf`: S3 bucket for log ingestion & S3 notification triggers
- `dynamodb.tf`: DynamoDB tables (`cloudlog_events`, `cloudlog_incidents`)
- `lambda.tf`: Lambda functions (Log Processor & API handlers)
- `sns.tf`: SNS topic & subscription for critical alert notifications
- `iam.tf`: Least-privilege IAM execution roles and policies
- `api_gateway.tf`: HTTP API Gateway routing

*Infrastructure code will be introduced incrementally in coordination with backend implementation.*
