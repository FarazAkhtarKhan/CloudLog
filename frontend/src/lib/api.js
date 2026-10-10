import { API_BASE_URL, MODE } from "../config";
import { currentSession, signOut } from "./auth";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, query } = {}) {
  const session = currentSession();
  const headers = { "Content-Type": "application/json" };
  if (MODE === "aws" && session?.token) headers.Authorization = `Bearer ${session.token}`;
  if (MODE === "local" && session) headers["X-User-Role"] = session.role;

  const params = new URLSearchParams(Object.entries(query || {}).filter(([, v]) => v !== undefined && v !== ""));
  const url = `${API_BASE_URL}${path}${params.size ? `?${params}` : ""}`;

  const unreachable = () => new ApiError(0, MODE === "local"
    ? "Can't reach the emulator on port 8000. Start it in another terminal: "
      + ".venv/bin/python -m backend.local.emulator --seed (or use npm run dev:aws for your AWS stack)"
    : "Can't reach API Gateway. Check VITE_API_URL in frontend/.env.aws.local and your network.");

  let response;
  try {
    response = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw unreachable();
  }
  if (response.status === 401) {
    signOut();
    window.location.reload();
  }
  const data = await response.json().catch(() => null);
  // The Vite dev proxy answers 502/504 with no JSON body when the emulator isn't running.
  if (!data && [502, 503, 504].includes(response.status)) throw unreachable();
  if (!response.ok) {
    throw new ApiError(response.status, data?.error || data?.message || `Request failed (${response.status})`);
  }
  return data;
}

export const api = {
  overview: () => request("/overview"),
  events: (filters) => request("/events", { query: filters }),
  incidents: (status) => request("/incidents", { query: { status, limit: 100 } }),
  incident: (id) => request(`/incidents/${id}`),
  triage: (id, action, note) => request(`/incidents/${id}`, { method: "PATCH", body: { action, note } }),
  runs: (limit = 20) => request("/pipeline/runs", { query: { limit } }),
  rules: () => request("/rules"),
  scenarios: () => request("/simulator/scenarios"),
  simulate: (body) => request("/simulator/runs", { method: "POST", body }),
  reset: () => request("/admin/reset", { method: "POST" }),
};
