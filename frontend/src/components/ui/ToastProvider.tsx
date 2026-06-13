import { useCallback, useMemo, useState, type ReactNode } from "react";

import { ToastContext, type ToastInput, type ToastTone } from "./useToast";

interface ToastItem extends ToastInput {
  id: number;
  tone: ToastTone;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const pushToast = useCallback((toast: ToastInput) => {
    const item: ToastItem = {
      id: Date.now() + Math.floor(Math.random() * 1000),
      tone: toast.tone ?? "info",
      ...toast,
    };

    setToasts((current) => [...current, item]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((candidate) => candidate.id !== item.id));
    }, 3800);
  }, []);

  const value = useMemo(() => ({ pushToast }), [pushToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.tone}`}>
            <strong>{toast.title}</strong>
            {toast.message ? <p>{toast.message}</p> : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

