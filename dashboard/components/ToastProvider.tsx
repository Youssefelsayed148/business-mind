"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

type ToastTone = "success" | "error" | "warning" | "info";
type Toast = { id: string; tone: ToastTone; message: string };

type ToastContextValue = {
  show: (tone: ToastTone, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const toneClasses: Record<ToastTone, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error: "border-red-200 bg-red-50 text-red-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info: "border-sky-200 bg-sky-50 text-sky-800",
};

const icons = {
  success: CheckCircle2,
  error: AlertTriangle,
  warning: AlertTriangle,
  info: Info,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback((tone: ToastTone, message: string) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((current) => [...current, { id, tone, message }].slice(-4));
    window.setTimeout(() => dismiss(id), 6000);
  }, [dismiss]);

  const value = useMemo<ToastContextValue>(() => ({
    show,
    success: (message) => show("success", message),
    error: (message) => show("error", message),
    warning: (message) => show("warning", message),
    info: (message) => show("info", message),
  }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed right-4 top-4 z-[80] grid w-[min(420px,calc(100vw-2rem))] gap-2">
        {toasts.map((toast) => {
          const Icon = icons[toast.tone];
          return (
            <div key={toast.id} className={`flex items-start gap-3 rounded-xl border p-3 shadow-lg shadow-slate-900/10 ${toneClasses[toast.tone]}`}>
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p className="min-w-0 flex-1 text-sm font-semibold leading-5">{toast.message}</p>
              <button type="button" onClick={() => dismiss(toast.id)} className="rounded-md p-1 opacity-70 hover:bg-white/60 hover:opacity-100" aria-label="Dismiss notification">
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
