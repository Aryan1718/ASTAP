import { ReactNode, useCallback, useMemo, useState } from "react";

import { ToastContext, ToastInput } from "../../hooks/useToast";
import { cn } from "../../lib/utils";

type ToastRecord = ToastInput & { id: number };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);

  const notify = useCallback((toast: ToastInput) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { ...toast, id }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((entry) => entry.id !== id));
    }, 3600);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-full max-w-sm flex-col gap-3">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "pointer-events-auto rounded-2xl border px-4 py-3 shadow-soft backdrop-blur",
              toast.tone === "success" && "border-emerald-200 bg-emerald-50 text-emerald-900",
              toast.tone === "error" && "border-red-200 bg-red-50 text-red-900",
              (!toast.tone || toast.tone === "info") && "border-line bg-white text-ink"
            )}
          >
            <p className="m-0 text-sm font-semibold">{toast.title}</p>
            {toast.description ? <p className="mt-1 text-sm text-current/80">{toast.description}</p> : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
