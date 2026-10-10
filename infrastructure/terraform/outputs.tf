output "aws_region" {
  value = var.aws_region
}

output "s3_log_bucket_name" {
  description = "Upload .jsonl log files here to trigger the processor"
  value       = aws_s3_bucket.log_bucket.id
}

output "api_gateway_endpoint" {
  description = "Base URL of the CloudLog HTTP API"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.auth_pool.id
}

output "cognito_user_pool_client_id" {
  value = aws_cognito_user_pool_client.web_client.id
}

output "dynamodb_tables" {
  value = {
    events    = aws_dynamodb_table.events.name
    incidents = aws_dynamodb_table.incidents.name
    runs      = aws_dynamodb_table.runs.name
  }
}

output "lambda_functions" {
  value = {
    processor = aws_lambda_function.processor.function_name
    api       = aws_lambda_function.api_handler.function_name
  }
}

output "sns_critical_alerts_topic_arn" {
  value = aws_sns_topic.critical_alerts.arn
}

output "processor_dlq_url" {
  value = aws_sqs_queue.processor_dlq.url
}

output "dashboard_bucket" {
  value = var.enable_dashboard_hosting ? aws_s3_bucket.dashboard[0].id : null
}

output "dashboard_distribution_id" {
  value = var.enable_dashboard_hosting ? aws_cloudfront_distribution.dashboard[0].id : null
}

output "dashboard_url" {
  description = "Public HTTPS URL of the dashboard (CloudFront)"
  value       = var.enable_dashboard_hosting ? "https://${aws_cloudfront_distribution.dashboard[0].domain_name}" : null
}

output "frontend_env" {
  description = "Paste into frontend/.env.local to point the dashboard at this deployment"
  value       = <<-EOT
    VITE_MODE=aws
    VITE_API_URL=${aws_apigatewayv2_stage.default.invoke_url}
    VITE_COGNITO_CLIENT_ID=${aws_cognito_user_pool_client.web_client.id}
    VITE_AWS_REGION=${var.aws_region}
  EOT
}
