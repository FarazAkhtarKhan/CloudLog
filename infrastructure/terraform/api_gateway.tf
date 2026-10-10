# HTTP API (v2): cheaper and lower latency than REST APIs, with a native JWT authorizer.
resource "aws_apigatewayv2_api" "http_api" {
  name          = "${var.project_name}-http-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "CloudLog dashboard API"

  cors_configuration {
    allow_headers = ["content-type", "authorization"]
    allow_methods = ["GET", "POST", "PATCH", "OPTIONS"]
    allow_origins = ["*"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true

  # Protects the Lambda (and the bill) from runaway clients.
  default_route_settings {
    throttling_rate_limit  = 50
    throttling_burst_limit = 100
  }
}

# Cognito tokens are verified here, at the edge, before any Lambda runs.
resource "aws_apigatewayv2_authorizer" "jwt_auth" {
  api_id           = aws_apigatewayv2_api.http_api.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "CognitoJWTAuthorizer"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web_client.id]
    issuer   = "https://${aws_cognito_user_pool.auth_pool.endpoint}"
  }
}

resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_handler.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

# Every route requires a valid JWT. Role checks happen in backend/handlers/auth.py.
resource "aws_apigatewayv2_route" "routes" {
  for_each = toset([
    "GET /me",
    "GET /overview",
    "GET /events",
    "GET /incidents",
    "GET /incidents/{id}",
    "PATCH /incidents/{id}",
    "GET /pipeline/runs",
    "GET /rules",
    "GET /simulator/scenarios",
    "POST /simulator/runs",
    "POST /admin/reset",
  ])

  api_id             = aws_apigatewayv2_api.http_api.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt_auth.id
  authorization_type = "JWT"
}
