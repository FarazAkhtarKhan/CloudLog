# Amazon CloudWatch Log Group for Lambda execution logs
# Explicit retention in days avoids indefinite log accumulation and charges
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-processor-${var.environment}"
  retention_in_days = var.log_retention_in_days
}
