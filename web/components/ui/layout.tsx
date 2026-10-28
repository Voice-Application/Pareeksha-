import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Eyebrow, one-sentence or noun title, supporting sentence, at most one primary action (00-shared 3). */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-4 gap-y-3 min-[860px]:flex-nowrap">
      <div className="min-w-0">
        <p className="eyebrow mb-1 min-h-[14px]">{eyebrow}</p>
        <h1 className="display text-xl font-semibold">{title}</h1>
        {description && <div className="mt-1 max-w-[68ch] text-base text-muted">{description}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  aux,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: ReactNode;
  aux?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} aria-label={typeof title === "string" ? title : undefined} className={cn("rounded-md border border-border bg-surface", className)}>
      {title && (
        <div className="flex h-11 items-center justify-between gap-2 border-b border-border px-4">
          <h2 className="text-md font-medium">{title}</h2>
          {aux && <div className="flex items-center gap-2 text-sm text-muted">{aux}</div>}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

/** Small neutral label (seed, demo, source, adapter). Neutral only: colour is reserved for measurements. */
export function Chip({ children, mono = false, className, title }: { children: ReactNode; mono?: boolean; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-xs border border-border bg-sunken px-1.5 text-xs text-muted",
        mono && "mono",
        className,
      )}
    >
      {children}
    </span>
  );
}
