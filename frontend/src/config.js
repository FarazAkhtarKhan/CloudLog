// CloudLog Frontend Configuration
// Configured to point to the live AWS API Gateway and Cognito User Pool

export const API_BASE_URL = (
  import.meta.env.VITE_API_URL || "https://yldbrm495e.execute-api.ap-south-1.amazonaws.com"
).replace(/\/+$/, "");

export const COGNITO_CLIENT_ID =
  import.meta.env.VITE_COGNITO_CLIENT_ID || "iufl9c8nnt2f3vd9jdif0bhh7";

export const COGNITO_REGION =
  import.meta.env.VITE_AWS_REGION || "ap-south-1";

export const COGNITO_ENDPOINT = `https://cognito-idp.${COGNITO_REGION}.amazonaws.com/`;

// Pre-seeded demo user accounts for rapid testing & evaluation
export const DEMO_ACCOUNTS = [
  {
    role: "Admin",
    email: "admin@cloudlog.local",
    password: "CloudLogAdmin#2026",
    description: "Full administrative access: view telemetry and resolve incidents",
    badgeColor: "#8b5cf6",
  },
  {
    role: "Analyst",
    email: "analyst@cloudlog.local",
    password: "CloudLogAnalyst#2026",
    description: "Operational access: view telemetry and resolve incidents",
    badgeColor: "#3b82f6",
  },
  {
    role: "Viewer",
    email: "viewer@cloudlog.local",
    password: "CloudLogViewer#2026",
    description: "Read-only access: view telemetry and incidents (cannot modify)",
    badgeColor: "#10b981",
  },
];
