output "s3_log_bucket_name" {
  description = "Name of the S3 bucket created for uploading raw JSONL log files"
  value       = aws_s3_bucket.log_bucket.id
}

output "s3_log_bucket_arn" {
  description = "ARN of the S3 raw log bucket"
  value       = aws_s3_bucket.log_bucket.arn
}

output "lambda_processor_name" {
  description = "Name of the log processor AWS Lambda function"
  value       = aws_lambda_function.processor.function_name
}

output "lambda_processor_arn" {
  description = "ARN of the log processor AWS Lambda function"
  value       = aws_lambda_function.processor.arn
}

output "dynamodb_events_table_name" {
  description = "Name of the DynamoDB table for log events"
  value       = aws_dynamodb_table.events.name
}

output "dynamodb_incidents_table_name" {
  description = "Name of the DynamoDB table for incidents"
  value       = aws_dynamodb_table.incidents.name
}

output "sns_critical_alerts_topic_arn" {
  description = "ARN of the Amazon SNS topic for critical incident notifications"
  value       = aws_sns_topic.critical_alerts.arn
}

output "cloudwatch_log_group_name" {
  description = "Name of the CloudWatch Log Group for Lambda logs"
  value       = aws_cloudwatch_log_group.lambda_logs.name
}

output "sns_critical_alerts_subscription_arn" {
  description = "ARN of the SNS critical alerts email subscription, if configured"
  value       = length(aws_sns_topic_subscription.critical_alerts_email) > 0 ? aws_sns_topic_subscription.critical_alerts_email[0].arn : null
}

output "api_gateway_endpoint" {
  description = "Base URL of the CloudLog HTTP API Gateway"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "cognito_user_pool_id" {
  description = "ID of the Cognito User Pool for CloudLog authentication"
  value       = aws_cognito_user_pool.auth_pool.id
}

output "cognito_user_pool_client_id" {
  description = "Client ID of the Cognito User Pool Client for web dashboard authentication"
  value       = aws_cognito_user_pool_client.web_client.id
}

