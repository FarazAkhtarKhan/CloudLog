// "local" talks to the offline emulator; "aws" talks to API Gateway + Cognito.
export const MODE = import.meta.env.VITE_MODE === "aws" ? "aws" : "local";

export const API_BASE_URL = MODE === "aws" ? (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "") : "";
export const AWS_REGION = import.meta.env.VITE_AWS_REGION || "ap-south-1";
export const COGNITO_CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID || "";
export const COGNITO_ENDPOINT = `https://cognito-idp.${AWS_REGION}.amazonaws.com/`;

export const POLL_MS = 4000;

export const ROLES = [
  {
    role: "Analyst",
    email: "analyst@cloudlog.local",
    password: "CloudLogAnalyst#2026",
    can: "Run simulations, acknowledge and resolve incidents.",
  },
  {
    role: "Admin",
    email: "admin@cloudlog.local",
    password: "CloudLogAdmin#2026",
    can: "Everything an analyst can do, plus reset the demo data.",
  },
  {
    role: "Viewer",
    email: "viewer@cloudlog.local",
    password: "CloudLogViewer#2026",
    can: "Read-only. Every change is refused by the API with 403.",
  },
];

export const LEVELS = ["CRITICAL", "ERROR", "WARNING", "INFO"];
