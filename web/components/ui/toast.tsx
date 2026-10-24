"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, X } from "lucide-react";
import { Button } from "./button";

type ToastItem = { id: number; message: string; tone: "info" | "error"; action?: { label: string; run: () => void } };
type Ctx = { toast: (message: string, opts?: { tone?: "info" | "error"; action?: ToastItem["action"] }) => void };

const ToastCtx = createContext<Ctx>({ toast: () => undefined });
export const useToast = () => useContext(ToastCtx);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const toast = useCallback<Ctx["toast"]>(
    (message, opts) => {
      const id = nextId++;
      setItems((xs) => [...xs, { id, message, tone: opts?.tone ?? "info", action: opts?.action }]);
      setTimeout(() => dismiss(id), 6000);
    },
    [dismiss],
  );
  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(360px,calc(100vw-32px))] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className="pointer-events-auto flex items-start gap-2 rounded-md border border-border bg-surface p-3 text-sm"
            style={{ boxShadow: "var(--shadow-float)" }}
          >
            {t.tone === "error" ? (
              <CircleAlert size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-fail-fg" aria-hidden />
            ) : (
              <CircleCheck size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-pass-fg" aria-hidden />
            )}
            <p className="flex-1">{t.message}</p>
            {t.action && (
              <Button
                variant="ghost"
                className="h-6 px-2"
                onClick={() => {
                  t.action?.run();
                  dismiss(t.id);
                }}
              >
                {t.action.label}
              </Button>
            )}
            <Button variant="ghost" icon className="h-6 w-6" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              <X size={14} strokeWidth={1.6} aria-hidden />
            </Button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
