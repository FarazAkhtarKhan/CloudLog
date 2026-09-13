# IAM Role assumed by the API Lambda
resource "aws_iam_role" "api_lambda_exec" {
  name = "${var.project_name}-api-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Least-Privilege IAM Policy for the API Lambda
resource "aws_iam_policy" "api_lambda_policy" {
  name        = "${var.project_name}-api-policy-${var.environment}"
  description = "Least privilege execution policy for the CloudLog API Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # 1. Read-only access to events table
      {
        Sid    = "DynamoDBEventsReadAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = aws_dynamodb_table.events.arn
      },

      # 2. Read and update access to incidents table + GSI
      {
        Sid    = "DynamoDBIncidentsAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.incidents.arn,
          "${aws_dynamodb_table.incidents.arn}/index/*"
        ]
      },

      # 3. CloudWatch logging permissions
      {
        Sid    = "CloudWatchLogging"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.api_lambda_logs.arn}:*"
      },

      # 4. S3 PutObject access for telemetry simulation
      {
        Sid    = "S3SimulationUploadAccess"
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.log_bucket.arn}/*"
      }
    ]
  })
}

# Attach policy to execution role
resource "aws_iam_role_policy_attachment" "api_lambda_policy_attach" {
  role       = aws_iam_role.api_lambda_exec.name
  policy_arn = aws_iam_policy.api_lambda_policy.arn
}

# CloudWatch Log Group for API Lambda execution logs
resource "aws_cloudwatch_log_group" "api_lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-api-${var.environment}"
  retention_in_days = var.log_retention_in_days
}

# AWS Lambda Function: API Controller
resource "aws_lambda_function" "api_handler" {
  function_name = "${var.project_name}-api-${var.environment}"
  description   = "Handles REST API Gateway requests for CloudLog dashboard"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  runtime = "python3.11"
  handler = "backend.api.handler.lambda_handler"

  role        = aws_iam_role.api_lambda_exec.arn
  memory_size = var.lambda_memory_size
  timeout     = 30

  environment {
    variables = {
      EVENTS_TABLE_NAME    = aws_dynamodb_table.events.name
      INCIDENTS_TABLE_NAME = aws_dynamodb_table.incidents.name
      S3_LOG_BUCKET        = aws_s3_bucket.log_bucket.bucket
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.api_lambda_policy_attach,
    aws_cloudwatch_log_group.api_lambda_logs,
  ]
}

# Permission allowing API Gateway to invoke the API Lambda
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}
