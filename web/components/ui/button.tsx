import Link from "next/link";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "destructive";

const base =
  "inline-flex h-8 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-sm border text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const variants: Record<Variant, string> = {
  primary: "border-accent bg-accent text-accent-on hover:opacity-90",
  secondary: "border-border-strong bg-surface text-fg hover:bg-hover",
  ghost: "border-transparent bg-transparent text-fg hover:bg-hover",
  destructive: "border-fail bg-surface text-fail-fg hover:bg-fail-tint",
};

export function buttonClass(variant: Variant = "secondary", icon = false, className?: string) {
  return cn(base, variants[variant], icon ? "w-8 px-0" : "px-3", className);
}

type Props = ComponentProps<"button"> & { variant?: Variant; icon?: boolean; loading?: boolean };

/** A loading button keeps its width (spinner replaces nothing, it is added in front). */
export function Button({ variant = "secondary", icon = false, loading = false, className, children, disabled, type = "button", ...rest }: Props) {
  return (
    <button type={type} disabled={disabled || loading} aria-busy={loading || undefined} className={buttonClass(variant, icon, className)} {...rest}>
      {loading && <span className="spinner" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ variant = "secondary", icon = false, className, ...rest }: ComponentProps<typeof Link> & { variant?: Variant; icon?: boolean }) {
  return <Link className={buttonClass(variant, icon, className)} {...rest} />;
}
