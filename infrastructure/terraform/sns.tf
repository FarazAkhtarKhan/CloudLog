# Amazon SNS Topic for dispatching real-time notifications for CRITICAL incidents
resource "aws_sns_topic" "critical_alerts" {
  name = "${var.project_name}-critical-alerts-${var.environment}"
}

# Optional email subscription for CRITICAL incident alerts (created only if alert_email is provided)
resource "aws_sns_topic_subscription" "critical_alerts_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.critical_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
