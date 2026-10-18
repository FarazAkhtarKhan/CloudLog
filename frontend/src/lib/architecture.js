import { MODE } from "../config";

const where = MODE === "aws" ? "AWS" : "Emulated";

// Every part of the system. `id` matches a part of the 3D model; `listed` parts appear on the Pipeline page.
export const PARTS = {
  source: {
    name: "Log source", role: "Services or the simulator",
    text: "Anything that writes JSON Lines log files: your services, the upload script, or the simulator on this dashboard.",
  },
  s3: {
    name: `${where} S3`, role: "Raw log bucket", listed: true,
    text: "Services drop JSON Lines files here. Every new .jsonl object emits an ObjectCreated event. Encrypted at rest, public access blocked.",
  },
  lambda: {
    name: `${where} Lambda`, role: "Log processor", listed: true,
    text: "Runs once per file, scales out automatically per upload. Validates each line, masks personal data, stores events and applies the detection rules.",
  },
  dynamo: {
    name: `${where} DynamoDB`, role: "Three on-demand tables", listed: true,
    text: "Events (partitioned by service, plus a per-day feed index), incidents (indexed by status) and pipeline runs. TTL deletes old data for free.",
  },
  sns: {
    name: `${where} SNS`, role: "Critical alert topic", listed: true,
    text: "Fans one message out to every subscriber (email, SMS, HTTPS) when an incident is critical, escalated or comes back.",
  },
  oncall: {
    name: "Subscribers", role: "On-call email",
    text: "Whoever is subscribed to the SNS topic. They are paged only for critical, escalated or reopened incidents.",
  },
  dashboard: {
    name: "React", role: "This dashboard",
    text: "Reads everything through the HTTP API every few seconds. Analysts acknowledge and resolve incidents from here.",
  },
  gateway: {
    name: MODE === "aws" ? "API Gateway + Cognito" : "Emulated gateway", role: "HTTP API with JWT authorizer", listed: true,
    text: "Verifies the sign-in token at the edge before any Lambda runs. Cognito groups map to Admin, Analyst and Viewer roles.",
  },
  api: {
    name: `${where} Lambda`, role: "API handler", listed: true,
    text: "Serves the dashboard, enforces role permissions and computes the statistics with a map, shuffle and reduce pass.",
  },
  dlq: {
    name: "Amazon SQS", role: "Dead-letter queue", listed: true,
    text: "If the processor still fails after Lambda's automatic retries, the S3 event is parked here instead of being lost.",
  },
  cloudwatch: {
    name: "Amazon CloudWatch", role: "Logs and alarms", listed: true,
    text: "Captures both functions' logs and raises an alarm to SNS when the processor reports errors or the DLQ fills up.",
  },
};
