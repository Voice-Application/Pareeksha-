"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, CircleCheck, CircleX, Scale, TriangleAlert } from "lucide-react";
import { RUBRIC, type CallDetailData, type CallEvaluation } from "@/lib/api/calls";
import { Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { Strip } from "@/components/ui/states";
import { EvidenceRef, FlagChip, Meter, Pips, ScoreChip, StatTile, TagChip, VerdictBadge, fmtScore, overallStep, verdictOf, type Threshold } from "@/components/ui/measure";
import { cn } from "@/lib/utils";

export function VerdictPanel({ ev, status, onOverride, onReevaluate, review }: { ev: CallEvaluation | null | undefined; status: CallDetailData["status"]; onOverride: () => void; onReevaluate: () => void; review: { reviewer: string; passed: boolean; critical: boolean } | null }) {
  if (!ev)
    return (
      <Panel title="Verdict">
        <p className="text-sm text-muted">{status === "in_progress" ? "Not scored yet. Scoring starts when the call ends." : status === "transcribing" ? "Transcribing. Scoring starts when the transcript is ready." : "Scoring in progress."}</p>
      </Panel>
    );
  if (ev.status === "judge_error")
    return (
      <Panel title="Verdict" aux={<span className="mono text-xs">{ev.rubric_version}</span>}>
        <Strip tone="error">
          The judge did not return a valid result. Deterministic checks are shown below.
          <div className="mt-2"><Button onClick={onReevaluate}>Re-evaluate</Button></div>
        </Strip>
      </Panel>
    );
  const score = ev.overall_score ?? null;
  const step = score === null ? null : overallStep(score);
  return (
    <Panel title="Verdict" aux={<span className="mono text-xs">{ev.rubric_version}</span>}>
      <div className="flex flex-wrap items-center gap-2">
        <VerdictBadge verdict={verdictOf(ev)} size="md" />
        {ev.needs_human_review && <FlagChip />}
        {ev.confidence === "low" && <Chip>Judge confidence low</Chip>}
      </div>
      <p className="eyebrow mt-4">Overall score</p>
      <p className="mono display text-2xl font-semibold" style={{ color: step && step <= 2 ? "var(--fail-fg)" : undefined }}>
        {fmtScore(score)} <span className="text-md font-normal text-muted">/ 100</span>
      </p>
      <div className="mt-2">
        <Meter value={score} width="100%" label={`Overall score ${fmtScore(score)} of 100, pass line 80`} />
        <div className="mono mt-1 flex justify-between text-xs text-subtle"><span>0</span><span className="ml-[70%] text-fg">pass 80</span><span>100</span></div>
      </div>
      {ev.review_reasons && ev.review_reasons.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Review reasons">
          {ev.review_reasons.map((r) => (
            <Chip key={r} mono className="h-6 border-fail text-fail-fg">{r}</Chip>
          ))}
        </div>
      )}
      {review && (
        <p className="mt-3 border-t border-border pt-3 text-sm">
          Human review by {review.reviewer}: <span className="font-medium">{review.critical ? "critical" : review.passed ? "pass" : "fail"}</span>
        </p>
      )}
      <div className="mt-4">
        <Button onClick={onOverride}>
          <Scale size={14} strokeWidth={1.6} aria-hidden />
          Override judge score
        </Button>
      </div>
    </Panel>
  );
}

export function FailureTagsPanel({ tags, onTurn, firstTurn }: { tags: { tag: string; count: number; level: "fail" | "warn" }[]; onTurn: (n: number) => void; firstTurn: Record<string, number | undefined> }) {
  return (
    <Panel title="Failure tags" aux={<span className="mono text-xs">{tags.length} type{tags.length === 1 ? "" : "s"}</span>}>
      {tags.length === 0 ? (
        <p className="text-sm text-subtle">The judge and the checks found no failure types.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <TagChip key={t.tag} tag={t.tag} level={t.level} count={t.count} turn={firstTurn[t.tag]} onTurn={onTurn} />
          ))}
        </div>
      )}
    </Panel>
  );
}

export function DimensionsPanel({ ev, onEvidence }: { ev: CallEvaluation; onEvidence: (turns: number[], label: string) => void }) {
  const dims = ev.dimensions ?? {};
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const sum = RUBRIC.reduce((a, d) => a + (dims[d.key] ? (d.weight * dims[d.key].score) / 4 : 0), 0);
  return (
    <Panel title="Dimension scores" aux={<span className="mono text-xs">weighted sum {fmtScore(Math.round(sum * 100) / 100)}</span>} bodyClassName="p-0">
      <ul>
        {RUBRIC.map((d) => {
          const v = dims[d.key];
          if (!v) return null;
          const pts = (d.weight * v.score) / 4;
          const showReason = v.score <= 2 || open[d.key];
          const turns = v.evidence_turns ?? [];
          return (
            <li key={d.key} className="border-b border-border px-4 py-3 last:border-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-sm font-medium">{d.label}</span>
                <span className="mono text-xs text-muted">{d.weight}%</span>
                {d.critical && v.score === 0 && <span className="inline-flex h-5 items-center rounded-xs bg-critical px-1.5 text-xs font-medium text-critical-on">critical</span>}
                <span className="mono ml-auto text-xs text-muted">{fmtScore(pts)} / {d.weight}</span>
                <ScoreChip score={v.score} kind="dimension" />
              </div>
              <div className="mt-2"><Pips score={v.score} /></div>
              {v.score > 2 && (
                <button type="button" className="mt-1 inline-flex items-center gap-1 text-xs text-muted hover:text-fg" aria-expanded={!!open[d.key]} onClick={() => setOpen((o) => ({ ...o, [d.key]: !o[d.key] }))}>
                  {open[d.key] ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}
                  {open[d.key] ? "Hide reason" : "Read reason"}
                </button>
              )}
              {showReason && <p className="mt-1.5 text-sm text-muted">{v.reason}</p>}
              {showReason &&
                (turns.length ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {turns.map((n) => (
                      <EvidenceRef key={n} turn={n} onSeek={() => onEvidence(turns, `Evidence ${evLabel(turns)}`)} />
                    ))}
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-subtle">No specific turn.</p>
                ))}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

export const evLabel = (turns: number[]) => (turns.length > 1 ? `#${Math.min(...turns)}-${Math.max(...turns)}` : `#${turns[0]}`);

export function ChecksPanel({ checks, onEvidence }: { checks: NonNullable<CallDetailData["checks"]>; onEvidence: (turns: number[], label: string) => void }) {
  const rank = (c: (typeof checks)[number]) => (c.passed === false && c.must_pass ? 0 : c.passed === false ? 1 : c.passed === null || c.passed === undefined ? 3 : 2);
  const sorted = [...checks].sort((a, b) => rank(a) - rank(b));
  const failed = checks.filter((c) => c.passed === false).length;
  const passed = checks.filter((c) => c.passed === true).length;
  return (
    <Panel title="Deterministic checks" aux={<span className="mono text-xs">{passed} passed, {failed} failed</span>} bodyClassName="p-0">
      {checks.length === 0 ? (
        <p className="p-4 text-sm text-subtle">No checks ran for this call.</p>
      ) : (
        <ul>
          {sorted.map((c) => {
            const Icon = c.passed === false ? CircleX : c.passed ? CircleCheck : TriangleAlert;
            return (
              <li key={`${c.check_type}:${c.check_key}`} className="grid grid-cols-[20px_1fr_auto] items-start gap-x-2 border-b border-border px-4 py-2.5 last:border-0">
                <Icon size={16} strokeWidth={1.6} className={cn("mt-0.5", c.passed === false ? "text-fail-fg" : c.passed ? "text-pass-fg" : "text-subtle")} aria-hidden />
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="mono text-sm">{c.check_key}</span>
                    {c.must_pass && <Chip>must pass</Chip>}
                    {(c.evidence_turns ?? []).map((n) => (
                      <EvidenceRef key={n} turn={n} onSeek={() => onEvidence(c.evidence_turns ?? [], `Evidence ${evLabel(c.evidence_turns ?? [n])}`)} />
                    ))}
                  </p>
                  <p className="text-xs text-muted">{c.detail || c.check_type}</p>
                </div>
                <span className={cn("text-xs font-medium", c.passed === false ? "text-fail-fg" : c.passed ? "text-pass-fg" : "text-subtle")}>{c.passed === false ? "Fail" : c.passed ? "Pass" : "Skipped"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

const sec = (ms: number | null | undefined) => (ms == null ? "-" : `${(ms / 1000).toFixed(1)} s`);
const thr = (ms: number | null | undefined, target: number): Threshold => (ms == null ? null : ms <= target ? "ok" : ms <= target * 1.25 ? "warn" : "fail");

export function MetricsPanel({ m, turns }: { m: CallDetailData["metrics"]; turns: NonNullable<CallDetailData["turns"]> }) {
  if (!m) return <Panel title="Metrics"><p className="text-sm text-subtle">Metrics are computed when the call ends.</p></Panel>;
  const att = m.barge_in_attempts;
  const agentTurns = turns.filter((t) => t.speaker === "agent").length;
  const ratio = m.agent_talk_ratio;
  const approx = m.latency_is_approximate;
  const lat = (ms: number | null | undefined) => (approx ? "-" : sec(ms));
  return (
    <Panel title="Metrics" bodyClassName="p-0">
      <dl className="grid grid-cols-2 [&>*]:border-b [&>*]:border-border [&>*:nth-child(odd)]:border-r [&>*:nth-last-child(-n+2)]:border-b-0">
        <StatTile label="Response p50" value={lat(m.response_latency_p50_ms)} threshold={approx ? null : thr(m.response_latency_p50_ms, 1000)} caption={approx ? "not measured on recordings" : "target under 1.0 s"} />
        <StatTile label="Response p95" value={lat(m.response_latency_p95_ms)} threshold={approx ? null : thr(m.response_latency_p95_ms, 2000)} caption={approx ? "not measured on recordings" : "target under 2.0 s"} />
        <StatTile label="First greeting" value={lat(m.first_greeting_ms)} threshold={approx ? null : thr(m.first_greeting_ms, 1500)} caption={approx ? "not measured on recordings" : "target under 1.5 s"} />
        <StatTile label="Barge-in honoured" value={att ? `${m.barge_in_honoured} of ${att}` : "none"} threshold={att ? (m.barge_in_honoured / att >= 0.9 ? "ok" : "fail") : null} caption={att ? "target at least 90%" : "caller did not interrupt"} />
        <StatTile label="Agent talk ratio" value={ratio == null ? "-" : `${Math.round(ratio * 100)}%`} caption="share of speech time" />
        <StatTile label="Turns" value={m.turn_count} caption={`${agentTurns} agent, ${m.turn_count - agentTurns} caller`} />
      </dl>
    </Panel>
  );
}
