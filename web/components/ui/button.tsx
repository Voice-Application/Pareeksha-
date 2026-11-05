import Link from "next/link";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "destructive";

/** Pill controls, 36px tall (app range). Hover is one colour step, press a 1px settle, focus the global ring. */
const base =
  "relative inline-flex h-9 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-pill border text-sm font-medium transition-[background-color,border-color,color,transform] duration-150 ease-out active:translate-y-px disabled:cursor-not-allowed disabled:opacity-55 disabled:active:translate-y-0 aria-busy:cursor-progress motion-reduce:transition-none motion-reduce:active:translate-y-0 before:absolute before:-inset-y-1 before:inset-x-0 before:content-['']";
const variants: Record<Variant, string> = {
  primary: "border-accent bg-accent text-accent-on hover:border-accent-hi hover:bg-accent-hi",
  secondary: "border-border-strong bg-surface text-fg hover:bg-hover",
  ghost: "border-transparent bg-transparent text-fg hover:bg-hover",
  destructive: "border-fail bg-surface text-fail-fg hover:bg-fail-tint",
};

export function buttonClass(variant: Variant = "secondary", icon = false, className?: string) {
  return cn(base, variants[variant], icon ? "w-9 px-0" : "px-4", className);
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
