# IAM Role assumed by the Lambda ingestion processor
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-processor-role-${var.environment}"

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

# Least-Privilege IAM Policy granting only the actions required by the processor
resource "aws_iam_policy" "lambda_policy" {
  name        = "${var.project_name}-processor-policy-${var.environment}"
  description = "Least privilege execution policy for the CloudLog ingestion processor Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # 1. Read access strictly to the raw log bucket
      {
        Sid    = "S3LogReadAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.log_bucket.arn}/*"
      },

      # 2. Write access to the cloudlog_events table
      {
        Sid    = "DynamoDBEventsWriteAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:BatchWriteItem"
        ]
        Resource = aws_dynamodb_table.events.arn
      },

      # 3. Read/write and GSI query access to the cloudlog_incidents table
      {
        Sid    = "DynamoDBIncidentsAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.incidents.arn,
          "${aws_dynamodb_table.incidents.arn}/index/*"
        ]
      },

      # 4. Publish access to the critical alerts SNS topic
      {
        Sid    = "SNSPublishAccess"
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.critical_alerts.arn
      },

      # 5. CloudWatch log streaming permissions
      {
        Sid    = "CloudWatchLogging"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.lambda_logs.arn}:*"
      }
    ]
  })
}

# Attach policy to execution role
resource "aws_iam_role_policy_attachment" "lambda_policy_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}
