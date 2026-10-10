# Amazon Cognito User Pool for CloudLog authentication
resource "aws_cognito_user_pool" "auth_pool" {
  name = "${var.project_name}-users-${var.environment}"

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  # Accounts are created by an administrator (or Terraform), never by self sign-up.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  auto_verified_attributes = []
}

# Cognito User Pool Client (Secretless for Single Page Application / Browser)
resource "aws_cognito_user_pool_client" "web_client" {
  name         = "${var.project_name}-web-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.auth_pool.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"
}

# Cognito User Groups for Role-Based Access Control (RBAC)
resource "aws_cognito_user_group" "admin" {
  name         = "Admin"
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  description  = "Analyst permissions plus resetting demo data"
  precedence   = 1
}

resource "aws_cognito_user_group" "analyst" {
  name         = "Analyst"
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  description  = "View everything, run simulations, acknowledge and resolve incidents"
  precedence   = 2
}

resource "aws_cognito_user_group" "viewer" {
  name         = "Viewer"
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  description  = "Read-only access to logs, incidents and pipeline runs"
  precedence   = 3
}

# ---------------------------------------------------------------------------
# Pre-seeded demo user accounts for rapid testing & evaluation
# ---------------------------------------------------------------------------

resource "aws_cognito_user" "demo_admin" {
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  username     = "admin@cloudlog.local"
  password     = "CloudLogAdmin#2026"

  attributes = {
    email          = "admin@cloudlog.local"
    email_verified = "true"
  }
}

resource "aws_cognito_user_in_group" "demo_admin_group" {
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  group_name   = aws_cognito_user_group.admin.name
  username     = aws_cognito_user.demo_admin.username
}

resource "aws_cognito_user" "demo_analyst" {
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  username     = "analyst@cloudlog.local"
  password     = "CloudLogAnalyst#2026"

  attributes = {
    email          = "analyst@cloudlog.local"
    email_verified = "true"
  }
}

resource "aws_cognito_user_in_group" "demo_analyst_group" {
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  group_name   = aws_cognito_user_group.analyst.name
  username     = aws_cognito_user.demo_analyst.username
}

resource "aws_cognito_user" "demo_viewer" {
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  username     = "viewer@cloudlog.local"
  password     = "CloudLogViewer#2026"

  attributes = {
    email          = "viewer@cloudlog.local"
    email_verified = "true"
  }
}

resource "aws_cognito_user_in_group" "demo_viewer_group" {
  user_pool_id = aws_cognito_user_pool.auth_pool.id
  group_name   = aws_cognito_user_group.viewer.name
  username     = aws_cognito_user.demo_viewer.username
}
