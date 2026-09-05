# Archive backend source code into a deployment ZIP package
# Excludes virtual environments, test files, git history, and terraform assets
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../.."
  output_path = "${path.module}/build/cloudlog_processor.zip"

  excludes = [
    ".git",
    ".git/**",
    ".venv",
    ".venv/**",
    ".pytest_cache",
    ".pytest_cache/**",
    "tests",
    "tests/**",
    "docs",
    "docs/**",
    "docker",
    "docker/**",
    "infrastructure",
    "infrastructure/**",
    "**/__pycache__",
    "**/__pycache__/**",
    "**/*.pyc",
    ".gitignore",
  ]
}

# AWS Lambda Function: Ingestion Processor
resource "aws_lambda_function" "processor" {
  function_name = "${var.project_name}-processor-${var.environment}"
  description   = "Processes raw JSONL logs from S3, extracts telemetry, indexes in DynamoDB, and alerts via SNS"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  runtime = "python3.11"
  handler = "backend.ingestion.handler.lambda_handler"

  role        = aws_iam_role.lambda_exec.arn
  memory_size = var.lambda_memory_size
  timeout     = var.lambda_timeout

  # Environment variables consumed by backend.common.config
  # Note: AWS_REGION is reserved and automatically provided by AWS Lambda runtime
  environment {
    variables = {
      EVENTS_TABLE_NAME    = aws_dynamodb_table.events.name
      INCIDENTS_TABLE_NAME = aws_dynamodb_table.incidents.name
      SNS_ALERT_TOPIC_ARN  = aws_sns_topic.critical_alerts.arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_policy_attach,
    aws_cloudwatch_log_group.lambda_logs,
  ]
}

# Resource-based policy allowing Amazon S3 to invoke the processor Lambda
resource "aws_lambda_permission" "s3_invoke_permission" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.log_bucket.arn
}
