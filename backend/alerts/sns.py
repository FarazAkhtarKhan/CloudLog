"""Amazon SNS alerting for critical incidents (email / SMS / HTTPS subscribers)."""
import logging
from typing import Any

import boto3

from backend.config import alert_topic_arn, aws_region

logger = logging.getLogger(__name__)


def alert_subject(incident: dict[str, Any]) -> str:
    prefix = "[CloudLog SECURITY]" if incident.get("category") == "Security" else "[CloudLog CRITICAL]"
    subject = f"{prefix} {incident['service']}: {incident['title']}"
    return subject if len(subject) <= 100 else subject[:97] + "..."  # SNS limit is 100


def alert_body(incident: dict[str, Any], reason: str) -> str:
    lines = [
        f"CloudLog detected a critical incident ({reason}).",
        "",
        f"Incident     {incident['incident_id']}",
        f"Service      {incident['service']}",
        f"Severity     {incident['severity']}  ({incident.get('category', 'Failure')})",
        f"Rule         {incident.get('rule_id', '-')}",
        f"Problem      {incident['title']}",
        f"Occurrences  {int(incident.get('occurrences', 1))}",
        f"Last seen    {incident.get('last_seen', '-')}",
    ]
    if incident.get("error_code"):
        lines.append(f"Error code   {incident['error_code']}")
    if incident.get("source_ip"):
        lines.append(f"Source IP    {incident['source_ip']}")
    lines += ["", "Acknowledge it from the CloudLog dashboard to stop the escalation clock."]
    return "\n".join(lines)


class AlertPublisher:
    def __init__(self, topic_arn: str | None = None, sns_client: Any | None = None):
        self.topic_arn = topic_arn if topic_arn is not None else alert_topic_arn()
        self.client = sns_client or boto3.client("sns", region_name=aws_region())

    def publish(self, incident: dict[str, Any], reason: str) -> str | None:
        """Publish an alert; returns the SNS MessageId, or None if no topic is configured."""
        if not self.topic_arn:
            logger.warning("SNS_ALERT_TOPIC_ARN not set; skipping alert for %s", incident["incident_id"])
            return None
        response = self.client.publish(
            TopicArn=self.topic_arn,
            Subject=alert_subject(incident),
            Message=alert_body(incident, reason),
            MessageAttributes={
                "severity": {"DataType": "String", "StringValue": incident["severity"]},
                "service": {"DataType": "String", "StringValue": incident["service"]},
            },
        )
        return response["MessageId"]
