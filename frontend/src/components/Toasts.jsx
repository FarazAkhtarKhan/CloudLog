import { X } from "lucide-react";
import { useCallback, useState } from "react";
import { ToastContext } from "../lib/toast";

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const dismiss = (id) => setToasts((t) => t.filter((x) => x.id !== id));
  const push = useCallback((title, detail, tone = "ok") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t.slice(-2), { id, title, detail, tone }]);
    setTimeout(() => dismiss(id), 6000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast" role="status">
            <span className={`bar bar-${t.tone}`} />
            <div>
              {t.title}
              {t.detail && <small>{t.detail}</small>}
            </div>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss"><X size={16} /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
