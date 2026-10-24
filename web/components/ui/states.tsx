import type { ReactNode } from "react";
import { CircleAlert, TriangleAlert, type LucideIcon } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/call";

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div aria-hidden className={cn("skeleton h-4", className)} style={style} />;
}

/** Skeleton rows with the final row height, announced once as busy. */
export function TableSkeleton({ rows = 5, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} aria-busy="true">
      <div className="h-9 border-b border-border bg-sunken" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-9 items-center gap-4 border-b border-border px-3 last:border-0">
          <Skeleton className="w-1/4" />
          <Skeleton className="w-1/6" />
          <Skeleton className="hidden w-1/6 min-[561px]:block" />
          <Skeleton className="hidden w-1/6 min-[561px]:block" />
        </div>
      ))}
    </div>
  );
}

export function FormSkeleton({ sections = 3 }: { sections?: number }) {
  return (
    <div role="status" aria-label="Loading" aria-busy="true" className="flex flex-col gap-6">
      {Array.from({ length: sections }, (_, i) => (
        <div key={i} className="rounded-md border border-border bg-surface p-4">
          <Skeleton className="mb-4 h-5 w-40" />
          <Skeleton className="mb-3 h-8 w-full" />
          <Skeleton className="h-8 w-2/3" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
  secondary,
}: {
  icon: LucideIcon;
  title: string;
  body: ReactNode;
  action?: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-[420px] flex-col items-center gap-2 px-4 py-12 text-center">
      <Icon size={24} strokeWidth={1.6} className="text-subtle" aria-hidden />
      <h3 className="text-md font-medium">{title}</h3>
      <p className="text-sm text-muted">{body}</p>
      {action && <div className="mt-2">{action}</div>}
      {secondary && <p className="text-xs text-subtle">{secondary}</p>}
    </div>
  );
}

function describe(error: unknown): { cause: string; requestId?: string } {
  if (error instanceof ApiError) return { cause: error.userMessage(), requestId: error.requestId };
  return { cause: "The API did not respond." };
}

/** Panel-level error: fail-tint strip, one-line cause, Retry, request id (00-shared 5.3). */
export function ErrorPanel({ error, onRetry, what }: { error: unknown; onRetry?: () => void; what?: string }) {
  const { cause, requestId } = describe(error);
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 border-l-2 border-fail bg-fail-tint px-4 py-3 text-sm">
      <CircleAlert size={16} strokeWidth={1.6} className="shrink-0 text-fail-fg" aria-hidden />
      <p className="min-w-0 flex-1">
        <span className="font-medium text-fail-fg">{what ? `Could not load ${what}. ` : ""}</span>
        <span>{cause}</span>
        {requestId && <span className="mono ml-2 text-xs text-muted">{requestId}</span>}
      </p>
      {onRetry && (
        <Button onClick={onRetry} variant="secondary">
          Retry
        </Button>
      )}
    </div>
  );
}

/** Inline form-level strip (save failed, preview failed). Amber variant for conflict/budget style warnings. */
export function Strip({ tone, children, onRetry }: { tone: "error" | "warn"; children: ReactNode; onRetry?: () => void }) {
  const Icon = tone === "error" ? CircleAlert : TriangleAlert;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 border-l-2 px-3 py-2 text-sm",
        tone === "error" ? "border-fail bg-fail-tint" : "border-warn bg-warn-tint",
      )}
    >
      <Icon size={16} strokeWidth={1.6} className={cn("mt-0.5 shrink-0", tone === "error" ? "text-fail-fg" : "text-warn-fg")} aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
      {onRetry && (
        <Button onClick={onRetry} className="h-6 px-2">
          Retry
        </Button>
      )}
    </div>
  );
}

/** Page-level error that replaces the content area but keeps the shell (00-shared 5.3). */
export function PageError({ error, onRetry, backHref, backLabel }: { error: unknown; onRetry?: () => void; backHref: string; backLabel: string }) {
  const notFound = error instanceof ApiError && error.status === 404;
  const forbidden = error instanceof ApiError && error.status === 403;
  const { requestId } = describe(error);
  return (
    <div role="alert" className="mx-auto flex max-w-[460px] flex-col items-center gap-2 py-16 text-center">
      <CircleAlert size={24} strokeWidth={1.6} className="text-fail-fg" aria-hidden />
      <h2 className="text-md font-medium">
        {notFound ? "This item does not exist or was deleted" : forbidden ? "This API key cannot read this" : "The API did not respond"}
      </h2>
      <p className="text-sm text-muted">{describe(error).cause}</p>
      {requestId && <p className="mono text-xs text-subtle">{requestId}</p>}
      <div className="mt-2 flex gap-2">
        {!notFound && onRetry && <Button onClick={onRetry}>Retry</Button>}
        <a className="inline-flex h-8 items-center rounded-sm px-3 text-sm text-accent-fg underline" href={backHref}>
          {backLabel}
        </a>
      </div>
    </div>
  );
}
