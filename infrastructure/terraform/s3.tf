# Generates a random hexadecimal suffix to avoid practical S3 bucket naming collisions
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# Raw log ingestion bucket
resource "aws_s3_bucket" "log_bucket" {
  bucket        = "${var.project_name}-raw-${random_id.bucket_suffix.hex}"
  force_destroy = true
}

# Enforce secure default: block all public access
resource "aws_s3_bucket_public_access_block" "log_bucket_public_block" {
  bucket = aws_s3_bucket.log_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Server-side encryption using standard AWS-managed keys (SSE-S3, zero extra cost)
resource "aws_s3_bucket_server_side_encryption_configuration" "log_bucket_encryption" {
  bucket = aws_s3_bucket.log_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Event Notification triggering the processor Lambda upon .jsonl file upload
resource "aws_s3_bucket_notification" "log_upload_notification" {
  bucket = aws_s3_bucket.log_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".jsonl"
  }

  depends_on = [aws_lambda_permission.s3_invoke_permission]
}
