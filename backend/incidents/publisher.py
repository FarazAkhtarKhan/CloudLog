"""
Amazon SNS Alert Publisher for CloudLog.
Formats and publishes real-time notifications for CRITICAL incidents.
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from backend.common.config import SEVERITY_CRITICAL, get_aws_region, get_sns_alert_topic_arn
from backend.incidents.models import Incident

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class SNSPublishResult:
    """Outcome of an SNS alert publishing attempt."""
    published: bool
    message_id: Optional[str] = None
    reason: Optional[str] = None
    subject: Optional[str] = None
    topic_arn: Optional[str] = None


def format_alert_subject(incident: Incident, max_len: int = 100) -> str:
    """
    Format a concise subject line for email and push notifications.
    Subject limit in SNS is 100 characters.
    """
    snippet = incident.message.strip()
    if len(snippet) > 60:
        snippet = snippet[:57] + "..."
    subject = f"[CRITICAL ALERT] {incident.service}: {snippet}"
    return subject[:max_len]


def format_alert_message(incident: Incident) -> str:
    """
    Format a clean, human-readable message body for email and mobile notifications.
    """
    lines = [
        "========================================",
        " CLOUDLOG CRITICAL INCIDENT ALERT",
        "========================================",
        f"Incident ID:     {incident.incident_id}",
        f"Service:         {incident.service}",
        f"Severity:        {incident.severity}",
        f"Status:          {incident.status}",
        f"Timestamp:       {incident.created_at}",
        f"Error Message:   {incident.message}",
    ]
    if incident.error_code:
        lines.append(f"Error Code:      {incident.error_code}")
    lines.extend([
        f"Source Event ID: {incident.source_event_id}",
        f"Source S3 URI:   {incident.source_s3_uri}",
        "========================================",
        "Action Required: Investigate immediately on CloudLog Dashboard.",
    ])
    return "\n".join(lines)


class SNSPublisher:
    """
    Publishes notifications to Amazon SNS for critical incidents.
    Encapsulates boto3 SNS calls and handles unconfigured topic ARNs gracefully.
    """

    def __init__(
        self,
        topic_arn: Optional[str] = None,
        sns_client: Optional[Any] = None,
    ) -> None:
        """
        Initialize the SNS Publisher.

        Args:
            topic_arn: SNS Topic ARN (defaults to SNS_ALERT_TOPIC_ARN env var).
            sns_client: Optional pre-configured boto3 SNS client (useful for Moto/testing).
        """
        self.topic_arn = topic_arn if topic_arn is not None else get_sns_alert_topic_arn()
        self.region_name = get_aws_region()

        if sns_client is not None:
            self._client = sns_client
        else:
            self._client = boto3.client("sns", region_name=self.region_name)

    def publish_critical_alert(self, incident: Incident) -> SNSPublishResult:
        """
        Publish an alert for a CRITICAL incident.

        Rules:
        - If severity is not CRITICAL: skip publishing.
        - If topic_arn is missing or empty: log warning and skip gracefully without crashing.
        - Otherwise: publish to SNS and return publish metadata.

        Args:
            incident: The Incident to evaluate and alert on.

        Returns:
            SNSPublishResult indicating whether the notification was published.
        """
        # 1. Enforce severity rule: Only CRITICAL incidents trigger SNS
        if incident.severity != SEVERITY_CRITICAL:
            logger.info(
                "Skipping SNS alert for non-critical incident %s (severity: %s)",
                incident.incident_id,
                incident.severity,
            )
            return SNSPublishResult(
                published=False,
                reason=f"Incident severity is {incident.severity}, not CRITICAL",
            )

        # 2. Check whether SNS Topic ARN is configured
        if not self.topic_arn or not self.topic_arn.strip():
            logger.warning(
                "SNS_ALERT_TOPIC_ARN is not configured. Skipping alert publication for incident %s",
                incident.incident_id,
            )
            return SNSPublishResult(
                published=False,
                reason="SNS_ALERT_TOPIC_ARN is not configured",
            )

        # 3. Format payload
        subject = format_alert_subject(incident)
        body = format_alert_message(incident)

        # 4. Publish to Amazon SNS
        try:
            response = self._client.publish(
                TopicArn=self.topic_arn,
                Subject=subject,
                Message=body,
            )
            message_id = response.get("MessageId")
            logger.info(
                "Published critical alert for incident %s to %s (MessageId: %s)",
                incident.incident_id,
                self.topic_arn,
                message_id,
            )
            return SNSPublishResult(
                published=True,
                message_id=message_id,
                subject=subject,
                topic_arn=self.topic_arn,
            )
        except ClientError as exc:
            logger.error("Failed to publish SNS alert to %s: %s", self.topic_arn, exc)
            raise exc
