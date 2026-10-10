# Dashboard hosting: private S3 bucket served through the CloudFront CDN.
# The bucket is never public; CloudFront reads it with Origin Access Control (OAC).
# Upload the built dashboard with scripts/deploy_dashboard.sh.

resource "aws_s3_bucket" "dashboard" {
  count         = var.enable_dashboard_hosting ? 1 : 0
  bucket        = "${var.project_name}-dashboard-${random_id.bucket_suffix.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "dashboard" {
  count                   = var.enable_dashboard_hosting ? 1 : 0
  bucket                  = aws_s3_bucket.dashboard[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "dashboard" {
  count                             = var.enable_dashboard_hosting ? 1 : 0
  name                              = "${var.project_name}-dashboard-oac-${var.environment}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "dashboard" {
  count               = var.enable_dashboard_hosting ? 1 : 0
  enabled             = true
  comment             = "CloudLog dashboard"
  default_root_object = "index.html"
  price_class         = "PriceClass_200" # includes edge locations in India

  origin {
    domain_name              = aws_s3_bucket.dashboard[0].bucket_regional_domain_name
    origin_id                = "dashboard-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard[0].id
  }

  default_cache_behavior {
    target_origin_id       = "dashboard-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # AWS managed "CachingOptimized"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "dashboard" {
  count  = var.enable_dashboard_hosting ? 1 : 0
  bucket = aws_s3_bucket.dashboard[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.dashboard[0].arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.dashboard[0].arn } }
    }]
  })
}
