"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Copy, FileText, PenLine } from "lucide-react";
import { ApiError } from "@/lib/api/call";
import { getQuickTest, improveQuickTest, inr, quickTestRefetch, retestQuickTest, verdictLine, type QuickTest, type QuickTestImprovement, type RuleResult } from "@/lib/api/quick-tests";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Chip, PageHeader, Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { Switch, TextAreaField } from "@/components/ui/field";
import { ScoreChip, ProgressBar, StatusPill } from "@/components/ui/measure";
import { PageError, Skeleton, Strip } from "@/components/ui/states";
import { useRouter } from "next/navigation";
import { RuleBadge } from "./status";

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

  return (
    <>
      <PageHeader
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
                <RuleRow key={r.id} rule={r} index={i} />
              ))}
            </ul>
          </Panel>
          <Conversations test={t} />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <Improve test={t} />
          <PromptPanel test={t} />
        </div>
      </div>
    </>
  );
}

const ORDER: Record<RuleResult["status"], number> = { broken: 0, pending: 1, kept: 2, not_tested: 3 };
/** Sort rules broken first, then pending, kept and not tested. */
const byStatus = (a: RuleResult, b: RuleResult) => ORDER[a.status] - ORDER[b.status];

/** One rule with its kept/broken counts and the evidence where it broke. */
function RuleRow({ rule, index = 0 }: { rule: RuleResult; index?: number }) {
  const evidence = rule.evidence ?? [];
  const checked = rule.broken + rule.kept;
  return (
    <li style={{ ["--i" as string]: index }} className="flex flex-col gap-3 px-5 py-4">
      <div className="flex items-start gap-3">
        <RuleBadge status={rule.status} />
        <div className="min-w-0 flex-1">
          <p className="text-base">{rule.text}</p>
          <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-muted">
            <span>{rule.kind === "forbidden" ? "Must never happen" : "Must always happen"}</span>
            {checked > 0 && <span>{rule.broken ? `broken in ${rule.broken} of ${checked} conversations` : `kept in ${checked} conversation${checked === 1 ? "" : "s"}`}</span>}
            {rule.source && rule.source !== "built-in" && <span className="truncate" title={rule.source}>from: “{rule.source}”</span>}
            {rule.source === "built-in" && <span>checked on every prompt</span>}
          </p>
        </div>
      </div>
      {evidence.length > 0 && (
        <ul className="ml-0 flex flex-col gap-2 min-[560px]:ml-[86px]">
          {evidence.slice(0, 3).map((e, i) => (
            <li key={`${e.call_id}-${i}`} className="rounded-sm bg-fail-tint px-4 py-3 text-sm">
              <p className="text-xs text-muted">
                In “{e.scenario}”{e.turn != null ? `, turn ${e.turn}` : ""} ·{" "}
                <Link className={linkCls} href={`/calls/${e.call_id}${e.turn != null ? `?turn=${e.turn}` : ""}`}>
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
                  {c.call_id ? (
                    <Link className="block truncate underline-offset-2 hover:underline" title={c.scenario} href={`/calls/${c.call_id}`}>
                      {c.scenario}
                    </Link>
                  ) : (
                    <span className="block truncate" title={c.scenario}>{c.scenario}</span>
                  )}
                  {c.error && <span className="block truncate text-xs text-fail-fg" title={c.error}>{c.error}</span>}
                </td>
                <td data-label="State"><StatusPill status={CONV_COPY[c.status]} /></td>
                <td data-label="Rules broken" title={(c.broken_rules ?? []).map((r) => rules.get(r) ?? r).join("; ")}>
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
  // Above the cost limit the API answers 402 with the estimate: show it, and run again once accepted.
  const [asked, setAsked] = useState<number | null>(null);
  const run = useMutation({
    mutationFn: () => retestQuickTest(test.id, asked !== null),
    onSuccess: (t) => router.push(`/test/${t.id}`),
    onError: (e) => {
      if (e instanceof ApiError && e.code === "confirm_cost") setAsked((e.details.estimate as { est_cost: number }).est_cost);
    },
  });
  return (
    <div className="mt-5 flex flex-col gap-4 border-t border-border pt-5">
      <p className="text-sm">{imp.summary}</p>
      <p className="num text-sm text-muted">
        {imp.prompt_chars_before.toLocaleString("en-IN")} → {imp.prompt_chars_after.toLocaleString("en-IN")} characters
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
        {imp.retest_id ? (
          <LinkButton href={`/test/${imp.retest_id}`} variant="primary">
            See its test <ArrowRight size={14} strokeWidth={1.6} aria-hidden />
          </LinkButton>
        ) : (
          <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>
            {asked !== null ? `Run for ${inr(asked)}` : "Test this prompt"}
          </Button>
        )}
      </div>
      {run.isError && asked === null && <Strip tone="error">{run.error instanceof ApiError ? run.error.userMessage() : "The API did not respond."}</Strip>}
    </div>
  );
}

/** The system prompt that was tested, collapsed by default. */
function PromptPanel({ test }: { test: QuickTest }) {
  return (
    <Panel title="What was tested">
      <details>
        <summary className="cursor-pointer text-sm font-medium">System prompt ({test.prompt_chars.toLocaleString("en-IN")} characters)</summary>
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-sm bg-sunken px-3 py-2 text-sm">{test.system_prompt}</pre>
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
            {brokenBefore} → {done ? brokenNow : "…"}
          </dd>
        </div>
        <div className={cell}>
          <dt className="label">Prompt size</dt>
          <dd className="display num text-xl">
            {p.prompt_chars.toLocaleString("en-IN")} → {test.prompt_chars.toLocaleString("en-IN")}
          </dd>
        </div>
        <div className={cell}>
          <dt className="label">Estimated cost</dt>
          <dd className="display num text-xl">
            {inr(p.est_cost)} → {inr(test.est_cost)}
          </dd>
        </div>
      </dl>
      <p className="px-5 pb-4 text-xs text-subtle">
        Same conversations on both prompts. <Link className={linkCls} href={`/runs/compare?base=${p.run_id}&head=${test.run_id}`}>Compare the scores in detail</Link>
      </p>
    </section>
  );
}
