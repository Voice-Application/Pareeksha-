"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, CircleCheck, CircleHelp, CircleX, Play, SquareCheckBig } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { listRunItems, listRuns } from "@/lib/api/runs";
import { asList, listPoll, listQuickTests } from "@/lib/api/quick-tests";
import { QuickStatus } from "@/components/quick/status";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { useNow } from "@/lib/hooks/use-now";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { LinkButton } from "@/components/ui/button";
import { EmptyState, ErrorPanel, Skeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { FlagChip, Meter, ScoreChip, StatTile, StatusPill, TileRow, VerdictBadge, fmtScore, verdictOf } from "@/components/ui/measure";
import { Chip } from "@/components/ui/layout";
import { useIsAdmin } from "@/components/layout/theme-toggle";
import { BarChart, DonutChart, LineChart } from "@/components/charts";
import { CHART_CATEGORICAL } from "@/components/charts/shared";

const STORE = "pareeksha.agent";

/** Every agent, page by page (at most 5 pages of 100), so many prompt-test agents cannot hide the user's own. */
async function allAgents() {
  const first = await call(api.GET("/api/v1/agents", { params: { query: { limit: 100 } } }));
  let items = first.items;
  let cursor = first.next_cursor;
  for (let page = 1; cursor && page < 5; page++) {
    const more = await call(api.GET("/api/v1/agents", { params: { query: { limit: 100, cursor } } }));
    items = [...items, ...more.items];
    cursor = more.next_cursor;
  }
  return { ...first, items };
}
/** Format credits as rupees, or a dash when unknown. */
const inr = (n: number | null | undefined) => (n == null ? "-" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const linkCls = "text-accent-fg underline-offset-2 hover:underline";

/** Panel contents for a query: a loading skeleton, an error with retry, an empty note, else the children. */
function PanelBody({ q, rows, empty, children }: { q: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; rows: number; empty: string; children: React.ReactNode }) {
  if (q.isPending)
    return (
      <div role="status" aria-label="Loading" aria-busy="true" className="flex flex-col gap-3">
        {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-6" />)}
      </div>
    );
  if (q.isError) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  if (!rows) return <p className="py-2 text-sm text-subtle">{empty}</p>;
  return <>{children}</>;
}

/** Loading placeholder for the overview header and stat tiles. */
export function OverviewSkeleton() {
  return (
    <>
      <PageHeader eyebrow="Overview" title="" description={<Skeleton className="h-4 w-72" />} />
      <TileRow cols="grid-cols-2 min-[860px]:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <div key={i} className="px-5 py-4"><Skeleton className="h-3 w-20" /><Skeleton className="mt-3 h-8 w-16" /></div>)}</TileRow>
    </>
  );
}


/** The home screen: it leads with the user's prompt tests (plus a "Get started" guide until one has finished),
 *  then the selected agent's run summary. Admins also get a separate "Platform" section at the bottom with
 *  the DLQ tile and platform-health telemetry; a non-admin (or an unknown role) never sees or fetches it. */
export function Overview() {
  const url = useUrlState();
  const now = useNow();
  // Platform health is SRE telemetry; show it only to an admin. An unknown/missing role is treated as
  // non-admin (so a member with a transient cookie gap never sees it or 403s fetching it) unless sign-in
  // is disabled, where the open dashboard acts as admin.
  const isAdmin = useIsAdmin();
  const agents = useQuery({ queryKey: ["agents", "overview"], queryFn: allAgents });
  // Agents made by Test my prompt have their own panel; the hero is about the user's own agents.
  const active = useMemo(() => (agents.data?.items ?? []).filter((a) => !a.archived && !(a.adapter_config as { quick_test_id?: string } | undefined)?.quick_test_id), [agents.data]);
  const promptTests = useQuery({ queryKey: ["quick-tests"], queryFn: listQuickTests });
  const urlAgent = url.get("agent");
  let stored = "";
  try { stored = typeof window !== "undefined" ? (window.localStorage.getItem(STORE) ?? "") : ""; } catch { /* storage unavailable */ }
  // With no explicit choice, open on the agent that ran most recently, not the first in the list.
  const newest = useQuery({ queryKey: ["runs", "overview", "newest"], queryFn: () => listRuns({ limit: 1 }) });
  const newestAgentId = newest.data?.items?.[0]?.agent_id;
  const agent = active.find((a) => a.id === urlAgent) ?? active.find((a) => a.id === stored) ?? active.find((a) => a.id === newestAgentId) ?? active[0];
  /** Switch the overview agent and remember it for the next visit. */
  const choose = (id: string) => {
    try { window.localStorage.setItem(STORE, id); } catch { /* convenience only */ }
    url.set({ agent: id });
  };

  const runs = useQuery({ queryKey: ["runs", "overview", agent?.id], enabled: !!agent, queryFn: () => listRuns({ agent_id: agent!.id, limit: 6 }), refetchOnWindowFocus: true });
  const latest = runs.data?.items?.find((r) => r.status !== "draft");
  const items = useQuery({ queryKey: ["run-items", latest?.id, "overview"], enabled: !!latest, queryFn: () => listRunItems(latest!.id) });
  const review = useQuery({ queryKey: ["calls", "needs-review", agent?.id], enabled: !!agent, queryFn: () => call(api.GET("/api/v1/calls", { params: { query: { agent_id: agent!.id, needs_review: true, reviewed: false, limit: 5 } } })) });
  // Platform metrics and health are SRE telemetry: fetch them only for elevated roles, so a member's
  // browser never requests the Kafka/outbox/consumer-lag payload (hiding the panel is not enough).
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => call(api.GET("/api/v1/metrics/summary")), enabled: isAdmin, refetchInterval: isAdmin ? 15000 : false });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => call(api.GET("/api/v1/usage")) });
  const health = useQuery({ queryKey: ["health"], queryFn: () => call(api.GET("/api/v1/health")), enabled: isAdmin, refetchInterval: isAdmin ? 15000 : false });

  if (agents.isError) return <><PageHeader eyebrow="Overview" title="Overview" /><ErrorPanel error={agents.error} what="agents" onRetry={() => void agents.refetch()} /></>;
  if (agents.isPending) return <OverviewSkeleton />;
  if (!agent) {
    const tested = asList(promptTests.data).length > 0;
    if (promptTests.isError && !tested)
      return (
        <>
          <PageHeader title="Your prompt tests" actions={<LinkButton variant="primary" href="/test"><SquareCheckBig size={14} strokeWidth={1.6} aria-hidden />Test my prompt</LinkButton>} />
          <ErrorPanel error={promptTests.error} what="prompt tests" onRetry={() => void promptTests.refetch()} />
        </>
      );
    if (promptTests.isPending)
      return <OverviewSkeleton />;
    return (
      <>
        <PageHeader
          title={tested ? "Your prompt tests" : "Test your first bot"}
          description={
            tested
              ? "Each test shows which rules in the prompt the bot kept and where it broke one. Voice bots on a phone line can be added as agents."
              : "Paste your bot's system prompt and Pareeksha chats with it as normal and tricky customers, then shows which of its rules it keeps and where it breaks them. Voice bots on a phone line can be added as agents."
          }
          actions={
            <>
              <LinkButton variant="primary" href="/test"><SquareCheckBig size={14} strokeWidth={1.6} aria-hidden />Test my prompt</LinkButton>
              <LinkButton href="/agents/new"><Bot size={14} strokeWidth={1.6} aria-hidden />Add a voice agent</LinkButton>
            </>
          }
        />
        {tested ? (
          <div className="max-w-[720px]"><PromptTests /></div>
        ) : (
          <Panel bodyClassName="p-0"><EmptyState icon={Bot} title="Nothing tested yet" body="Your tests and their results will show up here." action={<LinkButton variant="primary" href="/test"><SquareCheckBig size={14} strokeWidth={1.6} aria-hidden />Test my prompt</LinkButton>} /></Panel>
        )}
      </>
    );
  }

  // While a run is in flight the server summary is empty; fill the tiles from the items scored so far.
  const scoredNow = (items.data?.items ?? []).filter((i) => i.overall_score != null);
  const s = latest?.summary?.pass_rate != null || !scoredNow.length ? latest?.summary : { ...latest?.summary, pass_rate: scoredNow.filter((i) => i.passed).length / scoredNow.length, critical_failures: scoredNow.filter((i) => i.critical_failure).length };
  const running = latest && ["queued", "running"].includes(latest.status);
  const failed = latest && s?.pass_rate != null && latest.progress.evaluated ? Math.round(latest.progress.evaluated * (1 - s.pass_rate)) : 0;
  const crit = s?.critical_failures ?? 0;
  const title = !latest ? "No runs yet for this agent" : running ? `Run is ${latest.progress.evaluated + latest.progress.error} of ${latest.progress.total} done` : latest.progress.evaluated === 0 ? "Latest run has no scored calls" : failed === 0 ? `Latest run passed all ${latest.progress.evaluated} calls` : `Latest run passed ${latest.progress.evaluated - failed} of ${latest.progress.evaluated} calls${crit ? `, ${crit} critical` : ""}`;
  const desc = latest ? `Run "${latest.name || latest.id.slice(0, 8)}" ${latest.finished_at ? `finished ${relativeTime(latest.finished_at)}` : `was created ${relativeTime(latest.created_at)}`}.${s?.needs_review ? ` ${s.needs_review} call${s.needs_review === 1 ? " needs" : "s need"} human review.` : ""}` : "A run sends synthetic callers to your agent and scores every call.";

  const worst = [...(items.data?.items ?? [])].filter((i) => i.overall_score != null).sort((a, b) => a.overall_score! - b.overall_score!).slice(0, 5);
  const lag = metrics.data ? Math.max(0, ...Object.values(metrics.data.consumer_lag)) : 0;
  // Show the most lagging consumer groups only; a long tail of idle or test groups must not stretch the panel.
  const lagAll = Object.entries(metrics.data?.consumer_lag ?? {}).sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]));
  const lagRows = lagAll.slice(0, 6);
  const lagHidden = lagAll.length - lagRows.length;
  const stale = metrics.dataUpdatedAt && now && now - metrics.dataUpdatedAt > 45000;
  const budget = usage.data?.budget_credits;
  const budgetPct = budget ? Math.min(100, ((usage.data?.credits_used ?? 0) / budget) * 100) : 0;
  // The guide is for first-timers: hide it once any prompt test has finished (and while the list loads).
  const showGetStarted = !promptTests.isPending && !asList(promptTests.data).some((t) => t.status === "done");

  return (
    <>
      <PageHeader
        title="Your prompt tests"
        description="Paste your bot's system prompt and Pareeksha chats with it as normal and tricky customers, then shows which of its rules it keeps and where it breaks them."
        actions={<LinkButton variant="primary" href="/test"><SquareCheckBig size={14} strokeWidth={1.6} aria-hidden />Test my prompt</LinkButton>}
      />
      <div className={showGetStarted ? "mb-10 grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : "mb-10"}>
        <PromptTests />
        {showGetStarted && (
        <Panel title="Get started" label="Get started">
          <ol className="flex flex-col gap-4">
            <li className="flex gap-3">
              <span className="grid size-7 shrink-0 place-items-center rounded-pill bg-accent-tint text-sm font-medium text-accent-fg" aria-hidden>1</span>
              <div className="min-w-0"><p className="font-medium">Paste your bot&rsquo;s prompt</p><p className="text-sm text-muted">Open Test my prompt and drop in the system prompt your bot runs on.</p></div>
            </li>
            <li className="flex gap-3">
              <span className="grid size-7 shrink-0 place-items-center rounded-pill bg-accent-tint text-sm font-medium text-accent-fg" aria-hidden>2</span>
              <div className="min-w-0"><p className="font-medium">We role-play callers</p><p className="text-sm text-muted">Pareeksha chats as normal and tricky customers, in your languages.</p></div>
            </li>
            <li className="flex gap-3">
              <span className="grid size-7 shrink-0 place-items-center rounded-pill bg-accent-tint text-sm font-medium text-accent-fg" aria-hidden>3</span>
              <div className="min-w-0"><p className="font-medium">See what broke</p><p className="text-sm text-muted">Every rule the bot kept or broke, with the line it slipped on.</p></div>
            </li>
          </ol>
        </Panel>
        )}
      </div>

      <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-t border-border pt-8">
        <div className="min-w-0">
          <h2 className="display text-lg">{title}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span className="inline-flex items-center gap-2">
              <Bot size={16} strokeWidth={1.6} className="text-subtle" aria-hidden />
              {agent.name}
            </span>
            {active.length > 1 && <FilterSelect label="Agent" value={agent.id} onChange={choose} options={active.map((a) => ({ value: a.id, label: a.name }))} />}
          </div>
          <p className="mt-2 max-w-[68ch] text-base text-muted">{desc}</p>
        </div>
        <LinkButton href={`/runs/new?agent=${agent.id}`}><Play size={14} strokeWidth={1.6} aria-hidden />New run</LinkButton>
      </div>

      <TileRow cols="grid-cols-2 min-[860px]:grid-cols-3">
        <StatTile enter={0} href={latest ? `/runs/${latest.id}` : "/runs"} hero label={`Pass rate${running ? " so far" : ""}`} value={s?.pass_rate != null ? `${Math.round(s.pass_rate * 100)}%` : "-"} caption={latest ? `${latest.progress.evaluated} scored` : "no runs"} />
        <StatTile enter={1} href={latest ? `/runs/${latest.id}?verdict=critical` : "/runs"} label="Critical failures" value={s?.critical_failures ?? "-"} threshold={s?.critical_failures == null ? null : s.critical_failures > 0 ? "fail" : "ok"} caption="target 0" />
        <StatTile enter={2} label="Credits used" value={inr(usage.data?.credits_used)} caption={budget != null ? <span className="inline-flex items-center gap-2">of {inr(budget)} <Meter value={budgetPct} passLine={null} label={`Budget used: ${Math.round(budgetPct)}%, ${inr(usage.data?.credits_used ?? 0)} of ${inr(budget)}`} /></span> : "no budget set"} />
      </TileRow>

      <OverviewCharts runs={runs.data?.items ?? []} usage={usage.data?.items ?? []} usageError={usage.isError ? usage.error : undefined} onRetryUsage={() => void usage.refetch()} />

      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_380px]">
        <div className="stagger flex min-w-0 flex-col gap-6">
          <Panel title="Worst calls, latest run" aux={latest && <Link className={linkCls} href={`/runs/${latest.id}`}>Open run</Link>}>
            {!latest ? (
              <EmptyState icon={Play} title="No runs yet" body="A run sends synthetic callers to your agent." action={<LinkButton variant="primary" href={`/runs/new?agent=${agent.id}`}><Play size={14} strokeWidth={1.6} aria-hidden />Create run</LinkButton>} />
            ) : (
              <PanelBody q={items} rows={worst.length} empty="No scored calls in the latest run yet.">
                <ol className="flex flex-col divide-y divide-border">
                  {worst.map((i) => (
                    <li key={i.id} className="flex items-center gap-4 py-3 first:pt-1 last:pb-0">
                      <ScoreChip score={i.overall_score} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-base">{i.call_id ? <Link className="underline-offset-2 hover:underline" href={`/calls/${i.call_id}`}>{i.scenario}</Link> : i.scenario}</p>
                        <p className="flex min-w-0 flex-wrap gap-x-4 text-sm text-muted">
                          <span className="truncate">{i.persona}</span>
                          {i.noise_profile && <span className="truncate text-xs leading-5 text-subtle">line: <span className="mono">{i.noise_profile}</span></span>}
                        </p>
                      </div>
                      <VerdictBadge verdict={verdictOf(i)} />
                    </li>
                  ))}
                </ol>
              </PanelBody>
            )}
          </Panel>

          <Panel title="Recent runs" bodyClassName="p-0 pb-2" aux={<Link className={linkCls} href="/runs">All runs</Link>}>
            {runs.isPending || runs.isError || !runs.data?.items?.length ? (
              <div className="px-5 pb-5">
                <PanelBody q={runs} rows={runs.data?.items?.length ?? 0} empty="No runs yet.">{null}</PanelBody>
              </div>
            ) : (
              <table className="rt">
                <caption className="sr-only">Recent runs</caption>
                <thead><tr><th scope="col">Name</th><th scope="col">Status</th><th scope="col">Pass rate</th><th scope="col">When</th></tr></thead>
                <tbody>
                  {runs.data.items.slice(0, 5).map((r) => (
                    <tr key={r.id}>
                      <td className="max-w-[16rem]"><Link className="block truncate font-medium underline-offset-2 hover:underline" title={r.name || r.id} href={`/runs/${r.id}`}>{r.name || r.id.slice(0, 8)}</Link></td>
                      <td data-label="Status"><StatusPill status={r.status} /></td>
                      <td data-label="Pass rate">{r.summary?.pass_rate != null ? `${Math.round(r.summary.pass_rate * 100)}%` : "-"}</td>
                      <td data-label="When" className="text-muted"><time dateTime={r.created_at}>{relativeTime(r.created_at)}</time></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        <div className="stagger flex min-w-0 flex-col gap-6">
          <Panel title="Needs human review" aux={<Link className={linkCls} href="/calibration">Calibration</Link>}>
            <PanelBody q={review} rows={review.data?.items?.length ?? 0} empty="No calls are waiting for review.">
              <ul className="flex flex-col divide-y divide-border">
                {review.data?.items?.map((c) => (
                  <li key={c.id} className="flex flex-col gap-2 py-3 first:pt-1 last:pb-0">
                    <div className="flex items-center gap-3">
                      <ScoreChip score={c.overall_score} />
                      <Link className="mono text-sm underline-offset-2 hover:underline" href={`/calls/${c.id}`} aria-label={`Review call ${c.id.slice(0, 8)}${c.overall_score != null ? `, score ${fmtScore(c.overall_score)}` : ""}`}>{c.id.slice(0, 8)}</Link>
                      <span className="ml-auto"><FlagChip iconOnly reasons={c.review_reasons} /></span>
                    </div>
                    {(c.review_reasons ?? []).length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        {(c.review_reasons ?? []).slice(0, 2).map((x) => <Chip key={x} mono className="max-w-full truncate">{x}</Chip>)}
                        {(c.review_reasons ?? []).length > 2 && <span className="num text-xs text-muted" title={(c.review_reasons ?? []).slice(2).join(", ")}>+{(c.review_reasons ?? []).length - 2}</span>}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </PanelBody>
          </Panel>
        </div>
      </div>

      {/* Operational internals live apart from the run summary, and only elevated roles see (or fetch) them. */}
      {isAdmin && (
        <section aria-labelledby="overview-platform" className="mt-10 border-t border-border pt-8">
          <h2 id="overview-platform" className="label mb-4">Platform (admins only)</h2>
          <div className="max-w-[720px]">
            <TileRow cols="grid-cols-1">
              <StatTile href="/dlq" label="Open DLQ items" value={metrics.data?.dlq_open ?? "-"} threshold={metrics.data == null ? null : metrics.data.dlq_open > 0 ? "fail" : "ok"} caption="events that failed processing" />
            </TileRow>
            <Panel title="Platform health" aux={stale ? <span className="text-warn-fg">Last updated {relativeTime(new Date(metrics.dataUpdatedAt).toISOString())}</span> : undefined}>
              <PanelBody q={metrics} rows={1} empty="">
                <dl className="grid grid-cols-[1fr_auto] gap-x-4 text-sm [&>dd]:py-1.5 [&>dt]:py-1.5">
                  <dt className="text-muted">API</dt>
                  {/* The API row reports whether the health request itself got an answer; the database has its own row. */}
                  <dd><Status ok={health.isSuccess} fail={health.isError} label={health.isSuccess ? "ok" : health.isError ? "unreachable" : "unknown"} /></dd>
                  <dt className="text-muted">Database</dt>
                  <dd><Status ok={health.data?.db === "ok"} label={health.data?.db ?? "unknown"} /></dd>
                  <dt className="text-muted">Kafka</dt>
                  <dd><Status ok={health.data?.kafka === "ok"} fail={health.data?.kafka !== "ok" && !!health.data} label={health.data?.kafka ?? "unknown"} /></dd>
                  <dt className="text-muted">Outbox backlog</dt>
                  <dd className="num text-right">{metrics.data?.outbox_backlog ?? "-"}</dd>
                </dl>
                {lagRows.length > 0 && (
                  <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] gap-x-3 border-t border-border pt-3 text-sm [&>div>dd]:py-1 [&>div>dt]:truncate [&>div>dt]:py-1 max-[420px]:grid-cols-[minmax(0,1fr)_auto]">
                    {lagRows.map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="text-muted">Lag: <span className="mono text-xs">{k}</span></dt>
                        <dd className={v > 20 ? "num text-right text-warn-fg" : "num text-right"}>{v}</dd>
                      </div>
                    ))}
                    {lagHidden > 0 && <p className="col-span-full pt-1 text-xs text-subtle">and {lagHidden} more consumer group{lagHidden === 1 ? "" : "s"}</p>}
                    {lag > 20 && <p className="col-span-full pt-1 text-xs text-warn-fg">A consumer is more than 20 events behind.</p>}
                  </dl>
                )}
              </PanelBody>
            </Panel>
          </div>
        </section>
      )}
    </>
  );
}

/** The two measures a run exposes for charting, plus the identity used as the x label. */
type ChartRun = { id: string; name?: string | null; created_at: string; summary?: { pass_rate?: number | null; score_mean?: number | null } };
/** One usage row: tokens/characters/seconds spent per provider+operation. */
type UsageItem = { provider: string; operation: string; unit_type: string; units: number };

/** The LLM operations charted by name, in fixed caller→designer→judge order; each keeps its categorical
 *  slot (colour follows the entity). Every other llm_* operation (scenario generation, ...) is grouped as "Other". */
const TOKEN_OPS = ["llm_caller", "llm_designer", "llm_judge"];
const OTHER_OP = "other";

/** Pass rate (0–1) as a percent to one decimal; anything short of perfect never rounds up to 100. */
function passPct(rate: number): number {
  const v = Math.round(rate * 1000) / 10;
  return rate < 1 && v >= 100 ? 99.9 : v;
}

/** Turn an operation key (llm_caller) into a short readable label (Caller). */
function opLabel(op: string): string {
  if (op === OTHER_OP) return "Other";
  const m = op.replace(/^llm_/, "");
  return m.charAt(0).toUpperCase() + m.slice(1);
}

/**
 * The home dashboard's charts region: two run-based charts (mean-score trend and pass-rate per run,
 * two measures of different scale kept as two charts, never a dual axis) and — when token usage is
 * available — a token-usage-by-operation donut. Each chart is guarded so an empty data slice renders
 * nothing rather than a broken frame; the usage donut in particular stays hidden for members whose
 * usage payload carries no per-operation token rows. Built entirely from the plain-SVG chart module.
 */
function OverviewCharts({ runs, usage, usageError, onRetryUsage }: { runs: ChartRun[]; usage: UsageItem[]; usageError?: unknown; onRetryUsage: () => void }) {
  // Runs come newest-first; a trend reads left→right in time, so reverse, and keep only scored runs.
  const scored = useMemo(
    () => [...runs].reverse().filter((r) => r.summary?.score_mean != null || r.summary?.pass_rate != null),
    [runs],
  );
  const trend = useMemo(
    () => scored.filter((r) => r.summary?.score_mean != null).map((r) => ({ label: r.name || r.id.slice(0, 8), value: Math.round((r.summary!.score_mean as number) * 10) / 10 })),
    [scored],
  );
  const passRate = useMemo(
    () => scored.filter((r) => r.summary?.pass_rate != null).map((r) => ({ label: r.name || r.id.slice(0, 8), value: passPct(r.summary!.pass_rate as number) })),
    [scored],
  );

  // Token usage across every LLM operation: the named ones in fixed order, the rest grouped as "Other".
  // Colour is pinned to the operation, not its position, so it never shifts when one is absent.
  const tokenSlices = useMemo(() => {
    const byOp = new Map<string, number>();
    for (const u of usage) {
      if (u.unit_type !== "tokens" || !u.operation.startsWith("llm_")) continue;
      const op = TOKEN_OPS.includes(u.operation) ? u.operation : OTHER_OP;
      byOp.set(op, (byOp.get(op) ?? 0) + u.units);
    }
    return [...TOKEN_OPS, OTHER_OP]
      .map((op, i) => ({ label: opLabel(op), value: byOp.get(op) ?? 0, color: CHART_CATEGORICAL[i] }))
      .filter((s) => s.value > 0);
  }, [usage]);

  // Nothing scored yet, no token data and no usage failure → no charts region at all.
  if (!trend.length && !passRate.length && !tokenSlices.length && !usageError) return null;

  return (
    <div className="stagger mb-10 grid items-start gap-6 min-[900px]:grid-cols-2">
      {trend.length > 0 && (
        <Panel title="Mean score by run" label="Mean score by run">
          <LineChart points={trend} title="Mean score across recent runs, 0 to 100, with the pass line at 80" passLine={80} />
        </Panel>
      )}
      {passRate.length > 0 && (
        <Panel title="Pass rate by run" label="Pass rate by run">
          <BarChart bars={passRate} title="Pass rate per recent run, percent" valueSuffix="%" />
        </Panel>
      )}
      {/* Usage is project-wide (every agent), not the selected agent's, so the title says so. */}
      {(tokenSlices.length > 0 || usageError != null) && (
        <Panel title="Token usage by operation, all agents" label="Token usage by operation, all agents" className="min-[900px]:col-span-2">
          {tokenSlices.length > 0 ? (
            <DonutChart slices={tokenSlices} title="Share of tokens spent by LLM operation across all agents" centerLabel="tokens" unitLabel="tokens" />
          ) : (
            <ErrorPanel error={usageError} what="usage" onRetry={onRetryUsage} />
          )}
        </Panel>
      )}
    </div>
  );
}

/** The "Prompt tests" panel: the most recent quick tests with their rule-pass status, polled while any run. */
function PromptTests() {
  const q = useQuery({ queryKey: ["quick-tests"], queryFn: listQuickTests, refetchInterval: (s) => listPoll(s.state.data) });
  const list = asList(q.data);
  return (
    <Panel title="Prompt tests" aux={<Link className={linkCls} href="/test">Test my prompt</Link>}>
      <PanelBody q={q} rows={list.length} empty="No prompt tests yet. Paste a prompt in Test my prompt to start one.">
        <ul className="flex flex-col divide-y divide-border">
          {list.slice(0, 4).map((t) => (
            <li key={t.id} className="relative flex flex-col gap-1 py-3 first:pt-1 last:pb-0">
              <Link href={`/test/${t.id}`} className="truncate font-medium underline-offset-2 after:absolute after:inset-0 hover:underline">
                {t.name}
                {t.parent_id ? " (improved)" : ""}
              </Link>
              <span className="flex flex-wrap items-center gap-x-3 text-sm text-muted">
                <QuickStatus status={t.status} broken={t.rules_broken} total={t.rules_total} untested={t.rules_untested} />
                <time dateTime={t.created_at} className="text-subtle">{relativeTime(t.created_at)}</time>
              </span>
            </li>
          ))}
        </ul>
      </PanelBody>
    </Panel>
  );
}

/** A health row's state icon + label: a check when ok, a cross when failing, else a neutral unknown mark. */
function Status({ ok, label, fail }: { ok: boolean; label: string; fail?: boolean }) {
  const Icon = ok ? CircleCheck : fail ? CircleX : CircleHelp;
  return (
    <span className={fail ? "inline-flex items-center gap-1.5 text-fail-fg" : ok ? "inline-flex items-center gap-1.5 text-pass-fg" : "inline-flex items-center gap-1.5 text-muted"}>
      <Icon size={14} strokeWidth={1.6} aria-hidden />
      {label}
    </span>
  );
}
