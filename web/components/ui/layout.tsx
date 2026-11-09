"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { iconForPath } from "@/lib/nav-icons";
import { cn } from "@/lib/utils";

/**
 * Page head: the title states the page or its finding, then one muted context line, then the
 * supporting sentence. `eyebrow` is kept as the prop name for the context line (counts, the
 * breadcrumb, the agent), but it renders under the title, never as a label above it.
 *
 * A section icon is shown beside the title, resolved from the current route via the same map the
 * sidebar uses, so a page's glyph matches its nav row. Pass `icon` to override it, or `hideIcon`
 * to drop it (e.g. a finding-style title where a section glyph would mislead).
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  icon,
  hideIcon,
}: {
  eyebrow?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: LucideIcon;
  hideIcon?: boolean;
}) {
  const pathname = usePathname();
  const resolved = hideIcon ? undefined : (icon ?? iconForPath(pathname));
  return (
    <header className="rise-in mb-8 flex flex-wrap items-end justify-between gap-x-6 gap-y-4 min-[860px]:flex-nowrap">
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <TitleIcon icon={resolved} />
          <h1 className={title.length > 72 ? "display max-w-[40ch] text-lg" : "display max-w-[28ch] text-xl"}>{title}</h1>
        </div>
        {eyebrow ? <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">{eyebrow}</div> : null}
        {description && <div className="mt-2 max-w-[68ch] text-base text-muted">{description}</div>}
      </div>
      {actions && <div className="flex min-w-0 flex-wrap items-center gap-2 min-[860px]:shrink-0">{actions}</div>}
    </header>
  );
}

/** Renders the page's section icon in a tinted badge, or nothing when the route has no icon. */
function TitleIcon({ icon: Icon }: { icon?: LucideIcon }) {
  if (!Icon) return null;
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-sm bg-accent-tint text-accent-fg" aria-hidden>
      <Icon size={18} strokeWidth={1.6} />
    </span>
  );
}

/** One container recipe: a surface on the canvas, a hairline edge, the head inside without a rule under it. */
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
    <section id={id} aria-label={typeof title === "string" ? title : undefined} className={cn("rise-in relative min-w-0 rounded-md border border-border bg-surface transition-colors duration-150 hover:border-border-strong", className)}>
      {title && (
        <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-5 pt-3 pb-1">
          <h2 className="display text-md">{title}</h2>
          {aux && <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-muted">{aux}</div>}
        </div>
      )}
      <div className={cn("px-5 pt-2 pb-5", !title && "pt-5", bodyClassName)}>{children}</div>
    </section>
  );
}

/** Small neutral label (seed, demo, source, adapter, a failure code). Neutral only: colour is reserved for measurements. */
export function Chip({ children, mono = false, className, title }: { children: ReactNode; mono?: boolean; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-xs bg-sunken px-2 text-xs text-muted",
        mono && "mono text-2xs",
        className,
      )}
    >
      {children}
    </span>
  );
}
