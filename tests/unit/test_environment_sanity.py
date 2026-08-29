"""
Environment and Foundation Sanity Tests.
Verifies project configuration, constants, and sample fixtures.
"""
import json
from pathlib import Path
from backend.common.config import (
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
    SEVERITY_CRITICAL,
    VALID_SEVERITIES,
    DEFAULT_EVENTS_TABLE,
    DEFAULT_INCIDENTS_TABLE,
    get_events_table_name,
    get_incidents_table_name,
)


def test_config_defaults():
    """Verify backend default configurations and severity definitions."""
    assert SEVERITY_INFO == "INFO"
    assert SEVERITY_WARNING == "WARNING"
    assert SEVERITY_ERROR == "ERROR"
    assert SEVERITY_CRITICAL == "CRITICAL"
    assert len(VALID_SEVERITIES) == 4
    assert DEFAULT_EVENTS_TABLE == "cloudlog_events"
    assert DEFAULT_INCIDENTS_TABLE == "cloudlog_incidents"
    assert get_events_table_name() == "cloudlog_events_test"
    assert get_incidents_table_name() == "cloudlog_incidents_test"


def test_sample_log_fixtures_schema():
    """Verify sample log fixtures adhere to the defined MVP JSON log schema."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_log_events.json"
    assert fixtures_path.exists(), "Sample log fixtures file missing"

    with open(fixtures_path, "r", encoding="utf-8") as f:
        events = json.load(f)

    assert isinstance(events, list)
    assert len(events) == 4

    required_keys = {"timestamp", "service", "level", "message"}

    for event in events:
        assert required_keys.issubset(event.keys()), f"Event missing required keys: {event}"
        assert event["level"] in VALID_SEVERITIES, f"Invalid log level: {event['level']}"
        assert isinstance(event["service"], str)
        assert isinstance(event["message"], str)
