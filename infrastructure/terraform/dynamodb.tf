# DynamoDB Table 1: cloudlog_events
# Stores all validated telemetry partitioned by microservice and sorted by timestamp#event_id
resource "aws_dynamodb_table" "events" {
  name         = var.events_table_name
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "service"
  range_key = "sort_key"

  attribute {
    name = "service"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }
}

# DynamoDB Table 2: cloudlog_incidents
# Stores actionable problem tickets with GSI for dashboard open incident queries
resource "aws_dynamodb_table" "incidents" {
  name         = var.incidents_table_name
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  # Global Secondary Index: enables fast chronological querying of OPEN incidents
  global_secondary_index {
    name            = "status-created_at-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }
}
