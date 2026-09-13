# HTTP API Gateway (v2) for CloudLog Dashboard
resource "aws_apigatewayv2_api" "http_api" {
  name          = "${var.project_name}-http-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "Serverless HTTP API for CloudLog telemetry and incident management"

  cors_configuration {
    allow_headers = ["content-type", "authorization", "x-user-role"]
    allow_methods = ["GET", "PATCH", "POST", "OPTIONS"]
    allow_origins = ["*"]
    max_age       = 300
  }
}

# Auto-deploy default stage with access logging
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true
}

# Cognito JWT Authorizer
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

# Lambda Proxy Integration
resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_handler.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

# Protected Routes requiring Cognito JWT
resource "aws_apigatewayv2_route" "routes" {
  for_each = toset([
    "GET /events",
    "GET /events/critical",
    "GET /incidents",
    "GET /incidents/{id}",
    "PATCH /incidents/{id}",
    "GET /statistics",
    "GET /services",
    "POST /simulate"
  ])

  api_id             = aws_apigatewayv2_api.http_api.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt_auth.id
  authorization_type = "JWT"
}

# Unauthenticated Fallback route for CORS preflight OPTIONS requests
resource "aws_apigatewayv2_route" "options_fallback" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "OPTIONS /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}
