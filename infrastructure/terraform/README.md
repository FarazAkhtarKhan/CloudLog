# CloudLog AWS Infrastructure (Terraform)

This directory contains the **Terraform** configuration files used to provision all cloud infrastructure for the CloudLog system on Amazon Web Services (AWS).

The entire system is designed around **AWS Free Tier** serverless services, which means it costs **$0** when idle.

---

## Provisioned AWS Resources

| Configuration File | AWS Resource | Purpose |
| :--- | :--- | :--- |
| `s3.tf` | **Amazon S3** | Ingestion bucket where microservices drop `.jsonl` log files. Configured with event notifications. |
| `lambda.tf` | **AWS Lambda (Processor)** | Automatically triggered when a new file arrives in S3. Parses, classifies, and indexes logs. |
| `dynamodb.tf` | **Amazon DynamoDB** | Two tables: `cloudlog_events` (all logs) and `cloudlog_incidents` (errors and critical issues with a GSI). |
| `sns.tf` | **Amazon SNS** | Push notification topic for immediate alerts when critical incidents occur. |
| `cognito.tf` | **AWS Cognito** | Manages users and authentication (`Admin`, `Analyst`, `Viewer` roles). |
| `api_gateway.tf` | **Amazon API Gateway** | HTTP API v2 providing REST endpoints protected by Cognito JWT authentication. |
| `api_lambda.tf` | **AWS Lambda (API Handler)** | Backend controller that handles queries from the dashboard and simulation requests. |
| `iam.tf` | **AWS IAM** | Least-privilege roles and permissions for Lambda functions. |
| `cloudwatch.tf` | **Amazon CloudWatch** | Diagnostic log groups with 7-day retention to prevent storage costs. |

---

## How to Deploy the Infrastructure

### Prerequisites
* AWS CLI installed and configured with credentials:
  ```bash
  aws configure --profile terraform
  ```
* Terraform installed (`>= 1.5.0`).

### Commands

1. **Initialize Terraform:**
   ```bash
   AWS_PROFILE=terraform terraform init
   ```

2. **Preview Changes:**
   ```bash
   AWS_PROFILE=terraform terraform plan
   ```

3. **Deploy Resources:**
   ```bash
   AWS_PROFILE=terraform terraform apply -auto-approve
   ```

4. **Configure the frontend:**
   ```bash
   terraform output
   ```
   Copy `api_gateway_endpoint`, `cognito_user_pool_client_id`, and the AWS
   region into `frontend/.env.local` using `frontend/.env.example` as a template.

---

## How to Destroy Infrastructure (Stop All Billing)

When your evaluation or testing is complete, run this command to cleanly remove all AWS resources and ensure **zero ongoing charges**:

```bash
AWS_PROFILE=terraform terraform destroy -auto-approve
```

