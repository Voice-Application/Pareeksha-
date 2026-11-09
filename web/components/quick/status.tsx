import { CircleCheck, CircleX, Clock, Minus } from "lucide-react";
import type { QuickTest, RuleResult } from "@/lib/api/quick-tests";
import { cn } from "@/lib/utils";

/** A test's state in a few words: live while it runs, then how many rules broke. */
export function QuickStatus({ status, broken, total, untested = 0 }: { status: QuickTest["status"]; broken: number; total: number; untested?: number }) {
  const base = "inline-flex items-center gap-1.5 text-sm";
  if (status === "running" || status === "checking")
    return (
      <span className={cn(base, "text-fg")}>
        <span className="pulse-dot h-2 w-2 rounded-full bg-accent" aria-hidden />
        {status === "running" ? "running" : "checking answers"}
      </span>
    );
  if (status === "failed")
    return (
      <span className={cn(base, "text-fail-fg")}>
        <CircleX size={14} strokeWidth={1.6} aria-hidden />
        could not run
      </span>
    );
  if (broken)
    return (
      <span className={cn(base, "text-fail-fg")}>
        <CircleX size={14} strokeWidth={1.6} aria-hidden />
        {broken} of {total} rules broken
      </span>
    );
  if (untested)
    return (
      <span className={cn(base, "text-muted")}>
        <Minus size={14} strokeWidth={1.6} aria-hidden />
        {untested} of {total} rules not checked
      </span>
    );
  return (
    <span className={cn(base, "text-pass-fg")}>
      <CircleCheck size={14} strokeWidth={1.6} aria-hidden />
      all {total} rules kept
    </span>
  );
}

const RULE_COPY: Record<RuleResult["status"], string> = { broken: "Broken", kept: "Kept", pending: "Waiting", not_tested: "Not tested" };

/** Icon plus word for one rule; colour only for kept and broken. */
export function RuleBadge({ status }: { status: RuleResult["status"] }) {
  const base = "inline-flex h-6 shrink-0 items-center gap-1 rounded-pill px-2 text-xs font-medium whitespace-nowrap";
  if (status === "broken")
    return (
      <span className={cn(base, "bg-fail-tint text-fail-fg")}>
        <CircleX size={14} strokeWidth={1.6} aria-hidden />
        {RULE_COPY[status]}
      </span>
    );
  if (status === "kept")
    return (
      <span className={cn(base, "bg-pass-tint text-pass-fg")}>
        <CircleCheck size={14} strokeWidth={1.6} aria-hidden />
        {RULE_COPY[status]}
      </span>
    );
  const Icon = status === "pending" ? Clock : Minus;
  return (
    <span className={cn(base, "bg-sunken text-muted")}>
      <Icon size={14} strokeWidth={1.6} aria-hidden />
      {RULE_COPY[status]}
    </span>
  );
}
