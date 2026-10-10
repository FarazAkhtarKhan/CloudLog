# All tables are on-demand (PAY_PER_REQUEST): no capacity planning, scales with traffic,
# and costs nothing while idle. Schemas are mirrored by backend/local/resources.py.

# Every validated log line.
#   PK service | SK timestamp#event_id   -> one service's logs, newest first
#   GSI feed-index (feed_day, sort_key)  -> all services' logs for one day, newest first
resource "aws_dynamodb_table" "events" {
  name         = var.events_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "service"
  range_key    = "sort_key"

  attribute {
    name = "service"
    type = "S"
  }
  attribute {
    name = "sort_key"
    type = "S"
  }
  attribute {
    name = "feed_day"
    type = "S"
  }

  global_secondary_index {
    name            = "feed-index"
    hash_key        = "feed_day"
    range_key       = "sort_key"
    projection_type = "ALL"
  }

  # Logs expire automatically (EVENT_TTL_DAYS in backend/config.py); TTL deletes are free.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}

# One item per distinct problem (incident_id = "inc_" + fingerprint).
#   GSI status-updated_at-index -> incident queue per status, most recently changed first
resource "aws_dynamodb_table" "incidents" {
  name         = var.incidents_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "updated_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-updated_at-index"
    hash_key        = "status"
    range_key       = "updated_at"
    projection_type = "ALL"
  }

  # Incidents are the system of record for on-call work: keep 35 days of restore points.
  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

# One item per processed S3 file, used for the dashboard's pipeline trace.
#   PK stage ("processor") | SK started_at#run_id -> newest runs first
resource "aws_dynamodb_table" "runs" {
  name         = var.runs_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "stage"
  range_key    = "run_key"

  attribute {
    name = "stage"
    type = "S"
  }
  attribute {
    name = "run_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}
