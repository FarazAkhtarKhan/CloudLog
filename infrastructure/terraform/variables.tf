variable "aws_region" {
  type        = string
  description = "Target AWS region for deploying resources"
  default     = "ap-south-1"
}

variable "aws_profile" {
  type        = string
  description = "AWS CLI profile configured with credential_process"
  default     = "terraform"
}

variable "project_name" {
  type        = string
  description = "Project name prefix used for resource identification and tagging"
  default     = "cloudlog"
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier (e.g. dev, test, prod)"
  default     = "dev"
}

variable "events_table_name" {
  type        = string
  description = "Name of the DynamoDB table for log events"
  default     = "cloudlog_events"
}

variable "incidents_table_name" {
  type        = string
  description = "Name of the DynamoDB table for incidents"
  default     = "cloudlog_incidents"
}

variable "log_retention_in_days" {
  type        = number
  description = "CloudWatch log retention period in days to avoid unnecessary storage cost"
  default     = 7
}

variable "lambda_memory_size" {
  type        = number
  description = "Allocated memory size in MB for the ingestion processor Lambda"
  default     = 256
}

variable "lambda_timeout" {
  type        = number
  description = "Execution timeout in seconds for the ingestion processor Lambda"
  default     = 60
}

variable "alert_email" {
  type        = string
  description = "Optional email address to receive real-time notifications for CRITICAL incidents. Left empty by default."
  default     = ""
}
