# Dead-letter queue: S3 events the processor could not handle after Lambda's retries.
# Nothing is lost; an operator can inspect and replay them once the fault is fixed.
resource "aws_sqs_queue" "processor_dlq" {
  name                      = "${var.project_name}-processor-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days, the SQS maximum
  sqs_managed_sse_enabled   = true
}
