export function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const clock = (iso) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—";

export const dateTime = (iso) =>
  iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" }) : "—";

export function ms(value) {
  if (value === undefined || value === null) return "—";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

export function minutes(value) {
  if (value === undefined || value === null) return "—";
  if (value < 1) return `${Math.round(value * 60)} s`;
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)} min`;
  return `${Math.floor(value / 60)} h ${Math.round(value % 60)} min`;
}

export const number = (n) => (n ?? 0).toLocaleString();

export const fileName = (key = "") => key.split("/").pop();

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
