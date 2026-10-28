import type { LiveState } from "./use-run-live";

export function LiveIndicator({ state }: { state: LiveState }) {
  if (state === "closed") return null;
  const text = state === "live" ? "Live" : state === "polling" ? "Polling every 5 s" : state === "reconnecting" ? "Reconnecting" : "Connecting";
  return (
    <span role="status" className="inline-flex items-center gap-1.5 text-xs text-muted">
      <span className={state === "live" ? "pulse-dot h-2 w-2 rounded-full bg-accent" : "h-2 w-2 rounded-full border border-border-strong"} aria-hidden />
      {text}
    </span>
  );
}
