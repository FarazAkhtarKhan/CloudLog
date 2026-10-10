# Least-privilege role for the API Lambda: exactly the calls backend/handlers/api.py makes.
resource "aws_iam_role" "api_lambda_exec" {
  name = "${var.project_name}-api-role-${var.environment}"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_policy" "api_lambda_policy" {
  name        = "${var.project_name}-api-policy-${var.environment}"
  description = "CloudLog API: query tables, triage incidents, upload simulations, admin reset"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "QueryTables"
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.events.arn, "${aws_dynamodb_table.events.arn}/index/*",
          aws_dynamodb_table.incidents.arn, "${aws_dynamodb_table.incidents.arn}/index/*",
          aws_dynamodb_table.runs.arn,
        ]
      },
      {
        Sid      = "TriageIncidents"
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.incidents.arn
      },
      {
        # Only reachable through POST /admin/reset, which the API restricts to the Admin role
        Sid      = "AdminReset"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:BatchWriteItem"]
        Resource = [aws_dynamodb_table.events.arn, aws_dynamodb_table.incidents.arn, aws_dynamodb_table.runs.arn]
      },
      {
        Sid      = "UploadSimulations"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.log_bucket.arn}/raw-logs/simulations/*"
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.api_lambda_logs.arn}:*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_lambda_policy_attach" {
  role       = aws_iam_role.api_lambda_exec.name
  policy_arn = aws_iam_policy.api_lambda_policy.arn
}

# Lambda #2: serves the dashboard behind API Gateway.
resource "aws_lambda_function" "api_handler" {
  function_name = "${var.project_name}-api-${var.environment}"
  description   = "CloudLog dashboard API: queries, triage, simulations"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  handler          = "backend.handlers.api.lambda_handler"
  role             = aws_iam_role.api_lambda_exec.arn
  memory_size      = var.lambda_memory_size
  timeout          = 30

  environment {
    variables = {
      EVENTS_TABLE_NAME    = aws_dynamodb_table.events.name
      INCIDENTS_TABLE_NAME = aws_dynamodb_table.incidents.name
      RUNS_TABLE_NAME      = aws_dynamodb_table.runs.name
      S3_LOG_BUCKET        = aws_s3_bucket.log_bucket.bucket
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.api_lambda_policy_attach,
    aws_cloudwatch_log_group.api_lambda_logs,
  ]
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}
