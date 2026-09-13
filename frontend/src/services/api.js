import { API_BASE_URL } from "../config";
import { getIdToken, logout } from "./auth";

/**
 * Perform an authenticated HTTP request to the CloudLog API Gateway.
 */
async function fetchWithAuth(path, options = {}) {
  const token = getIdToken();
  if (!token) {
    throw new Error("No authentication token available. Please sign in.");
  }

  const url = `${API_BASE_URL}${path}`;
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    logout();
    window.location.reload();
    throw new Error("Session expired. Please sign in again.");
  }

  const data = await response.json();

  if (!response.ok) {
    const errorMsg = data.error || data.message || `Request failed with status ${response.status}`;
    throw new Error(errorMsg);
  }

  return data;
}

export async function getStatistics() {
  return fetchWithAuth("/statistics");
}

export async function getServices() {
  const data = await fetchWithAuth("/services");
  return data.services || [];
}

export async function getEvents({ limit = 50, level, service } = {}) {
  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (level) params.append("level", level);
  if (service) params.append("service", service);

  const query = params.toString() ? `?${params.toString()}` : "";
  const data = await fetchWithAuth(`/events${query}`);
  return data.events || [];
}

export async function getCriticalEvents({ limit = 50 } = {}) {
  const query = limit ? `?limit=${limit}` : "";
  const data = await fetchWithAuth(`/events/critical${query}`);
  return data.events || [];
}

export async function getIncidents({ status, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (status) params.append("status", status);

  const query = params.toString() ? `?${params.toString()}` : "";
  const data = await fetchWithAuth(`/incidents${query}`);
  return data.incidents || [];
}

export async function getIncident(id) {
  const data = await fetchWithAuth(`/incidents/${id}`);
  return data.incident;
}

export async function resolveIncident(id) {
  const data = await fetchWithAuth(`/incidents/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "RESOLVED" }),
  });
  return data.incident;
}

export async function simulateLog({ service, level, message, error_code } = {}) {
  const data = await fetchWithAuth("/simulate", {
    method: "POST",
    body: JSON.stringify({ service, level, message, error_code }),
  });
  return data;
}

