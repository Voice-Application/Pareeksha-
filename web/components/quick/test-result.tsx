"use client";

import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Copy, FileText, PenLine } from "lucide-react";
import { ApiError } from "@/lib/api/call";
import { getQuickTest, improveQuickTest, inr, quickTestRefetch, retestQuickTest, verdictLine, type CostEstimate, type QuickTest, type QuickTestImprovement, type RuleResult } from "@/lib/api/quick-tests";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Chip, PageHeader, Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { Switch, TextAreaField } from "@/components/ui/field";
import { ScoreChip, ProgressBar, StatusPill } from "@/components/ui/measure";
import { PageError, Skeleton, Strip } from "@/components/ui/states";
import { useRouter } from "next/navigation";
import { RuleBadge } from "./status";
import { CostConfirmDialog } from "./cost-confirm";

const linkCls = "text-accent-fg underline-offset-2 hover:underline";

/** Loading placeholder for a prompt test result. */
export function QuickTestResultSkeleton() {
  return (
    <div role="status" aria-label="Loading the test" aria-busy="true" className="flex flex-col gap-6">
      <Skeleton className="h-9 w-96 max-w-full" />
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** One test, live: rules kept or broken with the bot's own words, the conversations, and Improve. */
export function QuickTestResult({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["quick-test", id], queryFn: () => getQuickTest(id), refetchInterval: (s) => quickTestRefetch(s.state) });
  if (q.isError) return <PageError error={q.error} onRetry={() => void q.refetch()} backHref="/test" backLabel="Back to Test my prompt" />;
  if (!q.data) return <QuickTestResultSkeleton />;
  const t = q.data;
  const live = t.status === "running" || t.status === "checking";
  const broken = t.rules.filter((r) => r.status === "broken");
  const spans = locateSources(t.system_prompt, t.rules);

  return (
    <>
      <PageHeader
        // The title is the finding (e.g. "Broke 1 of 2 rules"), so a section glyph beside it would mislead.
        hideIcon
        title={verdictLine(t)}
        eyebrow={
          <>
            <span>{t.name}</span>
            <time dateTime={t.created_at}>{relativeTime(t.created_at)}</time>
            {t.parent_id && (
              <Link className={linkCls} href={`/test/${t.parent_id}`}>
                Earlier version of this prompt
              </Link>
            )}
            <Link className={linkCls} href={`/runs/${t.run_id}`}>
              Scores and full run
            </Link>
          </>
        }
        description={t.summary || undefined}
        actions={<LinkButton href="/test">New test</LinkButton>}
      />
      {live && (
        <div className="fade-in mb-6 max-w-[560px]" aria-live="polite">
          <ProgressBar done={t.status === "running" ? t.progress.finished : t.progress.checked} total={t.progress.total} label={t.status === "running" ? "Conversations finished" : "Conversations checked"} />
          <p className="mt-2 text-sm text-muted">This page updates by itself. You can leave it and come back; the test keeps running.</p>
        </div>
      )}
      {t.status === "failed" && (
        <div className="fade-in mb-6">
          <Strip tone="error">
            None of the conversations could run. {t.conversations.find((c) => c.error)?.error ?? "Check the AI key under Settings, LLM, and try again."}
          </Strip>
        </div>
      )}
      {t.parent_id && <Comparison test={t} />}

      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Panel title="Rules in your prompt" aux={<span>{broken.length ? `${broken.length} broken` : live ? "checking as conversations finish" : "none broken"}</span>} bodyClassName="p-0">
            <ul className="stagger flex flex-col divide-y divide-border">
              {[...t.rules].sort(byStatus).map((r, i) => (
                <RuleRow key={r.id} rule={r} index={i} located={spans.some((s) => s.id === r.id)} />
              ))}
            </ul>
          </Panel>
          <Conversations test={t} />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <Improve test={t} />
          <PromptPanel test={t} spans={spans} />
        </div>
      </div>
    </>
  );
}

const ORDER: Record<RuleResult["status"], number> = { broken: 0, pending: 1, kept: 2, not_tested: 3 };
/** Sort rules broken first, then pending, kept and not tested. */
const byStatus = (a: RuleResult, b: RuleResult) => ORDER[a.status] - ORDER[b.status];

/** Where a rule's source line sits in the tested prompt. */
type SourceSpan = { id: string; start: number; end: number; broken: boolean };

const PROMPT_ID = "tested-prompt";
/** The anchor id of a rule's highlighted source in the prompt panel. */
const sourceAnchor = (ruleId: string) => `prompt-src-${ruleId}`;

/**
 * Finds each rule's quoted source line in the prompt (case-insensitive, trailing punctuation ignored),
 * so the prompt can show the exact line a broken rule came from. The planner sometimes paraphrases;
 * a source that is not found verbatim is left as a plain quote. Overlapping matches keep the first.
 */
function locateSources(prompt: string, rules: RuleResult[]): SourceSpan[] {
  const hay = prompt.toLowerCase();
  const found: SourceSpan[] = [];
  for (const r of rules) {
    const needle = (r.source ?? "").trim().replace(/[.,;:!?…]+$/, "").toLowerCase();
    if (!needle || r.source === "built-in" || needle.length < 4) continue;
    const start = hay.indexOf(needle);
    if (start < 0) continue;
    found.push({ id: r.id, start, end: start + needle.length, broken: r.status === "broken" });
  }
  found.sort((a, b) => a.start - b.start);
  return found.filter((s, i) => i === 0 || s.start >= found[i - 1].end);
}

/** Opens the collapsed prompt so a jump to a highlighted source line lands on visible text. */
function openPrompt() {
  const el = document.getElementById(PROMPT_ID);
  if (el instanceof HTMLDetailsElement) el.open = true;
}

/** One rule with its kept/broken counts, a link to its line in the prompt, and the evidence where it broke. */
function RuleRow({ rule, index = 0, located = false }: { rule: RuleResult; index?: number; located?: boolean }) {
  const evidence = rule.evidence ?? [];
  const checked = rule.broken + rule.kept;
  const quoted = rule.source && rule.source !== "built-in";
  return (
    <li style={{ ["--i" as string]: index }} className="flex items-start gap-3 px-5 py-4">
      <RuleBadge status={rule.status} />
      {/* Evidence sits in the text column, so it lines up under the rule whatever the badge width. */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div>
          <p className="text-base">{rule.text}</p>
          <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-muted">
            <span>{rule.kind === "forbidden" ? "Must never happen" : "Must always happen"}</span>
            {checked > 0 && <span>{rule.broken ? `broken in ${rule.broken} of ${checked} conversations` : `kept in ${checked} conversation${checked === 1 ? "" : "s"}`}</span>}
            {quoted && located && (
              <a className={cn(linkCls, "min-w-0 truncate")} href={`#${sourceAnchor(rule.id)}`} onClick={openPrompt} title={rule.source}>
                from your prompt: “{rule.source}”
              </a>
            )}
            {quoted && !located && <span className="min-w-0 truncate" title={rule.source}>from: “{rule.source}”</span>}
            {rule.source === "built-in" && <span>checked on every prompt</span>}
          </p>
        </div>
        {evidence.length > 0 && (
          <ul className="flex flex-col gap-2">
            {evidence.slice(0, 3).map((e, i) => (
              <li key={`${e.call_id}-${i}`} className="rounded-sm bg-fail-tint px-4 py-3 text-sm">
                <p className="text-xs text-muted">
                  In “{e.scenario}”{e.turn != null ? `, turn ${e.turn}` : ""} ·{" "}
                  {/* Underlined: on the fail tint, colour alone does not set the link apart from the text (axe link-in-text-block). */}
                  <Link className="text-accent-fg underline underline-offset-2" href={`/calls/${e.call_id}${e.turn != null ? `?turn=${e.turn}` : ""}`}>
                    Read the conversation
                  </Link>
                </p>
                {e.quote && <blockquote className="mt-1 text-base">“{e.quote}”</blockquote>}
                {e.why && <p className="mt-1 text-muted">{e.why}</p>}
              </li>
            ))}
            {evidence.length > 3 && <li className="text-xs text-subtle">and {evidence.length - 3} more conversations</li>}
          </ul>
        )}
      </div>
    </li>
  );
}

const CONV_COPY: Record<QuickTest["conversations"][number]["status"], string> = { waiting: "queued", running: "running", checking: "evaluating", done: "completed", error: "error" };

/** The test's conversations and their status. */
function Conversations({ test }: { test: QuickTest }) {
  const rules = new Map(test.rules.map((r) => [r.id, r.text]));
  return (
    <Panel title="Conversations" aux={<span>{test.progress.total} in this test</span>} bodyClassName="p-0 pb-2">
      {test.conversations.length === 0 ? (
        <p className="px-5 pb-4 text-sm text-subtle">Starting the conversations…</p>
      ) : (
        <table className="rt">
          <caption className="sr-only">Test conversations</caption>
          <thead>
            <tr>
              <th scope="col">What the customer tried</th>
              <th scope="col">State</th>
              <th scope="col">Rules broken</th>
              <th scope="col">Score</th>
            </tr>
          </thead>
          <tbody>
            {test.conversations.map((c) => (
              <tr key={c.item_id}>
                <td className="max-w-[22rem]">
                  {/* One column wrapper: on phones .rt cells become flex rows, which would squeeze the name beside the chips. */}
                  <div className="flex w-full min-w-0 flex-col">
                  {c.call_id ? (
                    <Link className="block truncate underline-offset-2 hover:underline" title={c.scenario} href={`/calls/${c.call_id}`}>
                      {c.scenario}
                    </Link>
                  ) : (
                    <span className="block truncate" title={c.scenario}>{c.scenario}</span>
                  )}
                  {c.error && <span className="block truncate text-xs text-fail-fg" title={c.error}>{c.error}</span>}
                  {/* Name the broken rules in the row itself (not a hover title), so keyboard and screen-reader users get them too. */}
                  {c.status === "done" && (c.broken_rules ?? []).length > 0 && (
                    <ul aria-label="Rules it broke" className="mt-1.5 flex min-w-0 flex-wrap gap-1.5">
                      {(c.broken_rules ?? []).map((r) => (
                        <li key={r} className="max-w-full">
                          <span className="inline-flex max-w-full items-center rounded-xs bg-fail-tint px-2 py-0.5 text-xs text-fail-fg">
                            <span className="truncate">{rules.get(r) ?? r}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  </div>
                </td>
                <td data-label="State"><StatusPill status={CONV_COPY[c.status]} /></td>
                <td data-label="Rules broken">
                  {c.status !== "done" ? "-" : c.broken_rules?.length ? <span className="text-fail-fg">{c.broken_rules.length}</span> : "0"}
                </td>
                <td data-label="Score"><ScoreChip score={c.score} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

/** Form to ask for an improved prompt, optionally re-testing it. */
function Improve({ test }: { test: QuickTest }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [instructions, setInstructions] = useState("");
  const [retest, setRetest] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const finished = test.status === "done";
  const improve = useMutation({
    mutationFn: () => improveQuickTest(test.id, instructions, retest),
    onSuccess: (imp) => {
      void qc.invalidateQueries({ queryKey: ["quick-test", test.id] });
      void qc.invalidateQueries({ queryKey: ["quick-tests"] });
      if (imp.retest_id) router.push(`/test/${imp.retest_id}`);
    },
    onError: (e) => setError(e instanceof ApiError ? e.userMessage() : "The API did not respond."),
  });

  /** Request the improvement. */
  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    improve.mutate();
  }

  return (
    <Panel title="Improve the prompt">
      <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Improve the prompt">
        <TextAreaField
          id="qt-improve"
          label="What should change? (optional)"
          rows={3}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. Make it shorter. Stop it sharing the balance. Fix the documents."
          help="Leave empty to fix the broken rules and keep the prompt short."
        />
        <Switch label="Test the new prompt right away" checked={retest} onChange={setRetest} help="Runs the same conversations, so you can compare." />
        {error && <Strip tone="error">{error}</Strip>}
        <Button type="submit" variant="primary" loading={improve.isPending} disabled={!finished && !improve.isPending}>
          <PenLine size={14} strokeWidth={1.6} aria-hidden />
          {improve.isPending ? "Rewriting" : "Improve prompt"}
        </Button>
        {!finished && <p className="text-xs text-subtle">Available when the test has finished.</p>}
      </form>
      {test.improvement && <ImprovementView test={test} imp={test.improvement} />}
    </Panel>
  );
}

/** An improved prompt with its size change, a copy action and a cost-confirmed re-run. */
function ImprovementView({ test, imp }: { test: QuickTest; imp: QuickTestImprovement }) {
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const saved = imp.prompt_chars_before ? Math.round((1 - imp.prompt_chars_after / imp.prompt_chars_before) * 100) : 0;
  // Above the cost limit the API answers 402 with the estimate: ask in the shared dialog, then run confirmed.
  const [asked, setAsked] = useState<CostEstimate | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (confirmed: boolean) => retestQuickTest(test.id, confirmed),
    onSuccess: (t) => router.push(`/test/${t.id}`),
    onError: (e, confirmed) => {
      if (e instanceof ApiError && e.code === "confirm_cost" && !confirmed) {
        setAsked(e.details.estimate as CostEstimate);
        return;
      }
      const message = e instanceof ApiError ? e.userMessage() : "The API did not respond.";
      if (confirmed) setConfirmError(message);
      else setRunError(message);
    },
  });
  return (
    <div className="mt-5 flex flex-col gap-4 border-t border-border pt-5">
      <p className="text-sm">{imp.summary}</p>
      <p className="num text-sm text-muted">
        <Change before={imp.prompt_chars_before.toLocaleString("en-IN")} now={imp.prompt_chars_after.toLocaleString("en-IN")} /> characters
        {saved > 0 ? `, ${saved}% shorter` : saved < 0 ? `, ${-saved}% longer` : ""}
      </p>
      {(imp.changes ?? []).length > 0 && (
        <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
          {(imp.changes ?? []).map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      <details className="rounded-sm border border-border">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">The new prompt</summary>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap border-t border-border px-3 py-2 text-sm">{imp.improved_prompt}</pre>
      </details>
      {(imp.doc_suggestions ?? []).length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Suggested document fixes</h3>
          {(imp.doc_suggestions ?? []).map((d, i) => (
            <div key={i} className="rounded-sm bg-sunken px-3 py-2 text-sm">
              <p className="flex items-center gap-2 font-medium">
                <FileText size={14} strokeWidth={1.6} aria-hidden />
                {d.document}
              </p>
              <p className="mt-1 text-muted">{d.problem}</p>
              <p className="mt-1 whitespace-pre-wrap">{d.suggestion}</p>
            </div>
          ))}
          <p className="text-xs text-subtle">
            Apply them in <Link className={linkCls} href="/knowledge-bases">Documents</Link> (upload the corrected file), then test again.
          </p>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => {
            void navigator.clipboard?.writeText(imp.improved_prompt).then(() => setCopied(true));
          }}
        >
          {copied ? <Check size={14} strokeWidth={1.6} aria-hidden /> : <Copy size={14} strokeWidth={1.6} aria-hidden />}
          {copied ? "Copied" : "Copy prompt"}
        </Button>
        {/* The label swap is silent to screen readers; announce the copy here. */}
        <span className="sr-only" aria-live="polite">{copied ? "The new prompt is copied." : ""}</span>
        {imp.retest_id ? (
          <LinkButton href={`/test/${imp.retest_id}`} variant="primary">
            See its test <ArrowRight size={14} strokeWidth={1.6} aria-hidden />
          </LinkButton>
        ) : (
          <Button
            variant="primary"
            loading={run.isPending && !asked}
            onClick={() => {
              setRunError(null);
              run.mutate(false);
            }}
          >
            Test this prompt
          </Button>
        )}
      </div>
      {runError && <Strip tone="error">{runError}</Strip>}
      <CostConfirmDialog
        estimate={asked}
        running={run.isPending}
        error={confirmError}
        onClose={() => {
          setAsked(null);
          setConfirmError(null);
        }}
        onRun={() => {
          setConfirmError(null);
          run.mutate(true);
        }}
      />
    </div>
  );
}

/**
 * The tested system prompt, with each located rule source marked: broken rules in the fail tint,
 * the rest in a quiet accent tint. Collapsed by default; a rule's "from your prompt" link opens it
 * and jumps to the marked line. Opens by itself when a broken rule's line was found.
 */
function PromptPanel({ test, spans }: { test: QuickTest; spans: SourceSpan[] }) {
  const prompt = test.system_prompt;
  const anyBroken = spans.some((s) => s.broken);
  const parts: ReactNode[] = [];
  let at = 0;
  for (const s of spans) {
    if (s.start > at) parts.push(prompt.slice(at, s.start));
    parts.push(
      <mark
        key={s.id}
        id={sourceAnchor(s.id)}
        className={cn("scroll-mt-24 rounded-xs text-fg [box-decoration-break:clone] target:outline-2 target:outline-offset-1 target:outline-accent", s.broken ? "bg-fail-tint" : "bg-accent-tint")}
      >
        {s.broken && <span className="sr-only">Broken rule source: </span>}
        {prompt.slice(s.start, s.end)}
      </mark>,
    );
    at = s.end;
  }
  if (at < prompt.length) parts.push(prompt.slice(at));
  return (
    <Panel title="What was tested">
      <details id={PROMPT_ID} open={anyBroken || undefined}>
        <summary className="cursor-pointer text-sm font-medium">System prompt ({test.prompt_chars.toLocaleString("en-IN")} characters)</summary>
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-sm bg-sunken px-3 py-2 text-sm">{parts}</pre>
        {spans.length > 0 && (
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            {anyBroken && (
              <span className="inline-flex items-center gap-1.5">
                <span className="size-2.5 rounded-xs bg-fail-tint ring-1 ring-fail" aria-hidden />
                line a broken rule came from
              </span>
            )}
            {spans.some((s) => !s.broken) && (
              <span className="inline-flex items-center gap-1.5">
                <span className="size-2.5 rounded-xs bg-accent-tint ring-1 ring-accent" aria-hidden />
                other rules found
              </span>
            )}
          </p>
        )}
      </details>
      {test.user_details && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium">Test customer data</summary>
          <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-sm bg-sunken px-3 py-2 text-sm">{test.user_details}</pre>
        </details>
      )}
      <p className="mt-3 flex flex-wrap gap-2 text-sm text-muted">
        {test.kb_id && <Chip>with documents</Chip>}
        {test.language && <Chip mono>{test.language}</Chip>}
        {test.est_cost != null && <Chip>estimated {inr(test.est_cost)}</Chip>}
      </p>
    </Panel>
  );
}

/** A before → now value. The arrow is visual only; screen readers hear "was X, now Y" instead of "right arrow". */
function Change({ before, now, nowSr }: { before: ReactNode; now: ReactNode; nowSr?: string }) {
  return (
    <>
      <span aria-hidden>
        {before} → {now}
      </span>
      <span className="sr-only">
        was {before}, now {nowSr ?? now}
      </span>
    </>
  );
}

/** Before and after for an improved prompt: same conversations, so the numbers compare directly. */
function Comparison({ test }: { test: QuickTest }) {
  const parent = useQuery({ queryKey: ["quick-test", test.parent_id], enabled: !!test.parent_id, queryFn: () => getQuickTest(test.parent_id!) });
  if (!parent.data) return null;
  const p = parent.data;
  const brokenBefore = p.rules.filter((r) => r.status === "broken").length;
  const brokenNow = test.rules.filter((r) => r.status === "broken").length;
  const done = test.status === "done";
  const cell = "flex flex-col gap-1 px-5 py-4";
  return (
    <section aria-label="Compared with the earlier prompt" className="mb-6 rounded-md border border-border bg-surface">
      <h2 className="display px-5 pt-4 text-md">Compared with the earlier prompt</h2>
      <dl className="grid grid-cols-1 min-[640px]:grid-cols-3">
        <div className={cell}>
          <dt className="label">Rules broken</dt>
          <dd className={cn("display num text-xl", done && brokenNow < brokenBefore && "text-pass-fg", done && brokenNow > brokenBefore && "text-fail-fg")}>
            <Change before={brokenBefore} now={done ? brokenNow : "…"} nowSr={done ? undefined : "still checking"} />
          </dd>
        </div>
        <div className={cell}>
          <dt className="label">Prompt size</dt>
          <dd className="display num text-xl">
            <Change before={p.prompt_chars.toLocaleString("en-IN")} now={test.prompt_chars.toLocaleString("en-IN")} />
          </dd>
        </div>
        <div className={cell}>
          <dt className="label">Estimated cost</dt>
          <dd className="display num text-xl">
            <Change before={inr(p.est_cost)} now={inr(test.est_cost)} />
          </dd>
        </div>
      </dl>
      <p className="px-5 pb-4 text-xs text-subtle">
        Same conversations on both prompts. <Link className={linkCls} href={`/runs/compare?base=${p.run_id}&head=${test.run_id}`}>Compare the scores in detail</Link>
      </p>
    </section>
  );
}
