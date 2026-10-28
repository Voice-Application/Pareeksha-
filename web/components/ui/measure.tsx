import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { CircleCheck, CircleX, Clock, Flag, Minus, OctagonX, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/** Measurement components (direction 2.3-2.5, 00-shared 4). Colour here always means "this scored X". */

export type Step = 1 | 2 | 3 | 4 | 5;

/** Overall 0-100 to score-scale step; the pass line (80) sits between steps 3 and 4. */
export function overallStep(score: number): Step {
  return score < 40 ? 1 : score < 60 ? 2 : score < 80 ? 3 : score < 90 ? 4 : 5;
}
/** Dimension 0-4 to step 1-5. */
export function dimensionStep(score: number): Step {
  return (Math.max(0, Math.min(4, Math.round(score))) + 1) as Step;
}
export function stepStyle(step: Step | null): CSSProperties {
  return step === null
    ? { background: "var(--score-na)", color: "var(--score-na-on)" }
    : { background: `var(--score-${step})`, color: `var(--score-${step}-on)` };
}

export function fmtScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return "-";
  return String(Number(score.toFixed(2)));
}

/** Filled chip with the number printed on it. */
export function ScoreChip({ score, kind = "overall", className }: { score: number | null | undefined; kind?: "overall" | "dimension"; className?: string }) {
  const none = score === null || score === undefined;
  const step = none ? null : kind === "overall" ? overallStep(score) : dimensionStep(score);
  return (
    <span style={stepStyle(step)} className={cn("mono inline-flex h-5 min-w-8 items-center justify-center rounded-xs px-1.5 text-xs font-medium", className)} title={none ? "Not scored" : undefined}>
      {none ? "-" : kind === "dimension" ? `${score}/4` : fmtScore(score)}
    </span>
  );
}

export type Verdict = "pass" | "fail" | "critical";
export function verdictOf(e: { passed?: boolean | null; critical_failure?: boolean | null } | null | undefined): Verdict | null {
  if (!e || e.passed === null || e.passed === undefined) return e?.critical_failure ? "critical" : null;
  return e.critical_failure ? "critical" : e.passed ? "pass" : "fail";
}

/** Icon + word + colour. Critical is the only solid badge in the product. */
export function VerdictBadge({ verdict, size = "sm" }: { verdict: Verdict | null; size?: "sm" | "md" }) {
  if (!verdict) return <span className="text-subtle" title="Not scored">-</span>;
  const big = size === "md";
  const base = cn("inline-flex items-center gap-1 rounded-xs font-medium", big ? "h-7 px-2.5 text-sm" : "h-5 px-1.5 text-xs");
  const sz = big ? 16 : 14;
  if (verdict === "critical")
    return (
      <span className={cn(base, "bg-critical text-critical-on")}>
        <OctagonX size={sz} strokeWidth={1.6} aria-hidden />
        {big ? "Critical failure" : "Critical"}
      </span>
    );
  if (verdict === "fail")
    return (
      <span className={cn(base, "bg-fail-tint text-fail-fg")}>
        <CircleX size={sz} strokeWidth={1.6} aria-hidden />
        Fail
      </span>
    );
  return (
    <span className={cn(base, "bg-pass-tint text-pass-fg")}>
      <CircleCheck size={sz} strokeWidth={1.6} aria-hidden />
      Pass
    </span>
  );
}

/** needs_human_review is a flag, never a verdict. */
export function FlagChip({ reasons, iconOnly = false, label = "Needs human review" }: { reasons?: string[]; iconOnly?: boolean; label?: string }) {
  const title = reasons?.length ? reasons.join(", ") : label;
  if (iconOnly)
    return (
      <span title={title} aria-label={`${label}${reasons?.length ? `: ${reasons.join(", ")}` : ""}`} className="inline-flex h-5 w-5 items-center justify-center rounded-xs border border-border-strong text-warn-fg" role="img">
        <Flag size={12} strokeWidth={1.6} aria-hidden />
      </span>
    );
  return (
    <span className="inline-flex h-7 items-center gap-1.5 rounded-xs border border-border-strong px-2.5 text-sm">
      <Flag size={14} strokeWidth={1.6} className="text-warn-fg" aria-hidden />
      {label}
    </span>
  );
}

const STATUS_COPY: Record<string, string> = {
  draft: "draft",
  queued: "queued",
  connecting: "connecting",
  running: "running",
  in_progress: "in progress",
  transcribing: "transcribing",
  evaluating: "evaluating",
  completed: "completed",
  evaluated: "evaluated",
  partial: "partial",
  cancelled: "cancelled",
  failed: "failed",
  error: "error",
  judge_error: "judge error",
  skipped_budget: "skipped (budget)",
};
const ACTIVE = new Set(["running", "in_progress", "connecting", "transcribing", "evaluating"]);
const DONE = new Set(["completed", "evaluated", "partial"]);

export function StatusPill({ status }: { status: string }) {
  const label = STATUS_COPY[status] ?? status;
  const base = "inline-flex h-5 items-center gap-1.5 rounded-xs text-xs";
  if (ACTIVE.has(status))
    return (
      <span className={cn(base, "text-fg")}>
        <span className="pulse-dot h-2 w-2 rounded-full bg-accent" aria-hidden />
        {label}
      </span>
    );
  if (status === "error" || status === "failed" || status === "judge_error")
    return (
      <span className={cn(base, "text-fail-fg")}>
        <CircleX size={14} strokeWidth={1.6} aria-hidden />
        {label}
      </span>
    );
  if (DONE.has(status))
    return (
      <span className={cn(base, "text-muted")}>
        <CircleCheck size={14} strokeWidth={1.6} aria-hidden />
        {label}
      </span>
    );
  if (status === "cancelled" || status === "skipped_budget")
    return (
      <span className={cn(base, "text-muted")}>
        <Minus size={14} strokeWidth={1.6} aria-hidden />
        {label}
      </span>
    );
  return (
    <span className={cn(base, "text-muted")}>
      <Clock size={14} strokeWidth={1.6} aria-hidden />
      {label}
    </span>
  );
}

/** Track + fill + 2px ink tick at the pass line. Value and label are always printed by the caller. */
export function Meter({ value, max = 100, passLine = 80, width = 56, label }: { value: number | null | undefined; max?: number; passLine?: number | null; width?: number | string; label: string }) {
  const pct = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  const step = value === null || value === undefined ? null : overallStep((value / max) * 100);
  return (
    <span role="img" aria-label={label} className="relative inline-block h-2 rounded-full bg-sunken align-middle ring-1 ring-inset ring-border-strong" style={{ width }}>
      <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${pct}%`, background: step ? `var(--score-${step})` : "transparent" }} />
      {passLine !== null && <span className="absolute -inset-y-0.5 w-0.5 bg-fg" style={{ left: `${(passLine / max) * 100}%` }} aria-hidden />}
    </span>
  );
}

/** 4-segment bar for a 0-4 dimension score. */
export function Pips({ score }: { score: number }) {
  const step = dimensionStep(score);
  return (
    <span className="flex gap-1" role="img" aria-label={`${score} of 4`}>
      {[0, 1, 2, 3].map((i) => (
        <span key={i} className="h-1.5 flex-1 rounded-xs" style={{ background: i < score ? `var(--score-${step})` : "var(--bg-sunken)" }} />
      ))}
    </span>
  );
}

export function ProgressBar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total ? Math.min(100, (done / total) * 100) : 0;
  return (
    <span className="flex items-center gap-2">
      <span role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} className="h-1 w-full min-w-12 overflow-hidden rounded-xs bg-sunken">
        <span className="block h-full bg-accent" style={{ width: `${pct}%` }} />
      </span>
      <span className="mono whitespace-nowrap text-xs text-muted">
        {done}/{total}
      </span>
    </span>
  );
}

export type Threshold = "ok" | "warn" | "fail" | null;
export function StatTile({ label, value, caption, threshold = null, hero = false, href }: { label: string; value: ReactNode; caption?: ReactNode; threshold?: Threshold; hero?: boolean; href?: string }) {
  const Icon = threshold === "ok" ? CircleCheck : threshold === "warn" ? TriangleAlert : threshold === "fail" ? CircleX : null;
  const tone = threshold === "ok" ? "text-pass-fg" : threshold === "warn" ? "text-warn-fg" : threshold === "fail" ? "text-fail-fg" : "";
  return (
    <div className={cn("relative flex min-w-0 flex-col gap-0.5 px-4 py-3", href && "hover:bg-hover")}>
      <dt className="eyebrow">{href ? <Link href={href} className="after:absolute after:inset-0">{label}</Link> : label}</dt>
      <dd className="flex flex-col gap-0.5">
        <span className={cn("mono flex items-center gap-1.5 font-medium", hero ? "text-2xl" : "text-lg", tone)}>
          {Icon && <Icon size={16} strokeWidth={1.6} aria-label={threshold === "ok" ? "meets target" : threshold === "warn" ? "near target" : "misses target"} role="img" />}
          {value}
        </span>
        {caption && <span className="text-xs text-subtle">{caption}</span>}
      </dd>
    </div>
  );
}

/** A row of StatTiles separated by hairlines (MetaStrip-style dl). */
export function TileRow({ children, cols }: { children: ReactNode; cols?: string }) {
  return (
    <dl className={cn("mb-6 grid divide-x divide-border overflow-hidden rounded-md border border-border bg-surface max-[860px]:grid-cols-2 max-[860px]:divide-x-0", cols ?? "grid-cols-2 min-[860px]:grid-cols-3 min-[1180px]:grid-cols-6")}>{children}</dl>
  );
}

export const failureTypeCopy: Record<string, string> = {
  intent_miss: "The agent missed what the caller wanted.",
  asr_misrecognition: "The agent's speech recognition heard the wrong words or numbers.",
  wrong_fact: "The agent stated or confirmed a fact that is wrong.",
  tool_selection: "The agent called the wrong tool, or none when one was needed.",
  tool_arguments: "The agent called the right tool with wrong arguments.",
  missing_disclosure: "A mandatory disclosure was not said in time.",
  policy_violation: "The agent broke a policy or said a forbidden phrase.",
  language_mismatch: "The agent answered in a language the caller did not use.",
  latency: "The agent took too long to respond.",
  interruption_handling: "The agent did not stop when the caller interrupted.",
  loop: "The agent repeated itself without progress.",
  escalation_error: "The agent escalated when it should not have, or failed to when it should.",
  hallucination: "The agent invented information it was not given.",
  prompt_injection: "The caller changed the agent's behaviour with injected instructions.",
};

/** Mono failure tag with icon; cross for failure-level, triangle for warning-level (2/4). */
export function TagChip({ tag, level = "fail", count, turn, onTurn }: { tag: string; level?: "fail" | "warn"; count?: number; turn?: number; onTurn?: (n: number) => void }) {
  const Icon = level === "fail" ? CircleX : TriangleAlert;
  return (
    <span title={failureTypeCopy[tag] ?? tag} className={cn("mono inline-flex h-6 items-center gap-1 rounded-xs border px-1.5 text-xs", level === "fail" ? "border-fail bg-fail-tint text-fail-fg" : "border-warn bg-warn-tint text-warn-fg")}>
      <Icon size={12} strokeWidth={1.6} aria-hidden />
      {tag}
      {count !== undefined && count > 1 && <span className="text-muted">x{count}</span>}
      {turn !== undefined && (onTurn ? <EvidenceRef turn={turn} onSeek={onTurn} /> : <span className="text-muted">#{turn}</span>)}
    </span>
  );
}

/** Mono #n button: seeks audio and scrolls the transcript on the call page. */
export function EvidenceRef({ turn, onSeek, href }: { turn: number; onSeek?: (n: number) => void; href?: string }) {
  const cls = "mono inline-flex h-5 min-w-6 items-center justify-center rounded-xs border border-border-strong bg-surface px-1 text-xs text-accent-fg hover:bg-hover";
  if (href)
    return (
      <a href={href} className={cls} aria-label={`Evidence turn ${turn}`}>
        #{turn}
      </a>
    );
  return (
    <button type="button" className={cls} onClick={() => onSeek?.(turn)} aria-label={`Seek to turn ${turn}`}>
      #{turn}
    </button>
  );
}
