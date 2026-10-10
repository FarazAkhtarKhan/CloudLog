# One deployment package for both functions: only the backend/ package is needed.
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../.."
  output_path = "${path.module}/build/cloudlog_backend.zip"

  excludes = [
    ".git", ".git/**", ".github", ".github/**", ".venv", ".venv/**", ".pytest_cache", ".pytest_cache/**",
    ".ruff_cache", ".ruff_cache/**", "frontend", "frontend/**", "infrastructure", "infrastructure/**",
    "tests", "tests/**", "docs", "docs/**", "scripts", "scripts/**", "deploy", "deploy/**",
    "backend/local", "backend/local/**", "node_modules", "node_modules/**",
    "**/__pycache__", "**/__pycache__/**", "**/*.pyc",
    ".gitignore", ".dockerignore", "Dockerfile", "README.md", "package.json", "package-lock.json",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
  ]
}

# Lambda #1: invoked by S3 for every new .jsonl object.
resource "aws_lambda_function" "processor" {
  function_name = "${var.project_name}-processor-${var.environment}"
  description   = "Validates S3 log files, stores events, detects incidents and sends SNS alerts"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  handler          = "backend.handlers.processor.lambda_handler"
  role             = aws_iam_role.lambda_exec.arn
  memory_size      = var.lambda_memory_size
  timeout          = var.lambda_timeout

  environment {
    variables = {
      EVENTS_TABLE_NAME    = aws_dynamodb_table.events.name
      INCIDENTS_TABLE_NAME = aws_dynamodb_table.incidents.name
      RUNS_TABLE_NAME      = aws_dynamodb_table.runs.name
      SNS_ALERT_TOPIC_ARN  = aws_sns_topic.critical_alerts.arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_policy_attach,
    aws_cloudwatch_log_group.lambda_logs,
  ]
}

# S3 invokes Lambda asynchronously: retry twice, then park the event in the DLQ.
resource "aws_lambda_function_event_invoke_config" "processor" {
  function_name                = aws_lambda_function.processor.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.processor_dlq.arn
    }
  }
}

resource "aws_lambda_permission" "s3_invoke_permission" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.log_bucket.arn
}
