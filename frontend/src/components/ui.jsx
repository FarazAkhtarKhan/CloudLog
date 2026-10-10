import { AlertCircle } from "lucide-react";

export const Sev = ({ level }) => <span className={`sev sev-${level}`}>{level}</span>;

const STATUS_LABEL = { OPEN: "Open", ACKNOWLEDGED: "Acknowledged", RESOLVED: "Resolved", SUCCESS: "Processed", FAILED: "Failed" };
export const Status = ({ value }) => <span className={`status status-${value}`}>{STATUS_LABEL[value] || value}</span>;

export function Switch({ checked, onChange, children }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className="switch" onClick={() => onChange(!checked)}>
      <span className="switch-track" aria-hidden="true" />
      {children}
    </button>
  );
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
          {o.count !== undefined && <span className="count num">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Panel({ title, aside, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || aside) && (
        <header className="panel-head">
          {title && <h2>{title}</h2>}
          {aside && <div className="aside">{aside}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export const Empty = ({ title, children }) => (
  <div className="empty">
    <strong>{title}</strong>
    {children}
  </div>
);

export const ErrorNotice = ({ error }) =>
  error ? (
    <div className="notice notice-error" role="alert">
      <AlertCircle size={18} aria-hidden="true" />
      <span>{error.message}</span>
    </div>
  ) : null;
