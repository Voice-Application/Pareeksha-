"use client";

import Link from "next/link";
import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, Play } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { listRunItems, listRuns } from "@/lib/api/runs";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { useNow } from "@/lib/hooks/use-now";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { LinkButton } from "@/components/ui/button";
import { EmptyState, ErrorPanel, Skeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { FlagChip, Meter, ScoreChip, StatTile, StatusPill, TileRow, VerdictBadge, verdictOf } from "@/components/ui/measure";
import { Chip } from "@/components/ui/layout";

const STORE = "pareeksha.agent";
const inr = (n: number | null | undefined) => (n == null ? "-" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);

function PanelBody({ q, rows, empty, children }: { q: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; rows: number; empty: string; children: React.ReactNode }) {
  if (q.isPending)
    return (
      <div role="status" aria-label="Loading" aria-busy="true" className="flex flex-col gap-2">
        {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-5" />)}
      </div>
    );
  if (q.isError) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  if (!rows) return <p className="text-sm text-subtle">{empty}</p>;
  return <>{children}</>;
}

export function OverviewSkeleton() {
  return (
    <>
      <PageHeader eyebrow="Overview" title="" description={<Skeleton className="h-4 w-72" />} />
      <TileRow cols="grid-cols-2 min-[860px]:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <div key={i} className="px-4 py-3"><Skeleton className="h-3 w-20" /><Skeleton className="mt-2 h-6 w-16" /></div>)}</TileRow>
    </>
  );
}

export function Overview() {
  const url = useUrlState();
  const now = useNow();
  const agents = useQuery({ queryKey: ["agents", "overview"], queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 100 } } })) });
  const active = useMemo(() => (agents.data?.items ?? []).filter((a) => !a.archived), [agents.data]);
  const urlAgent = url.get("agent");
  let stored = "";
  try { stored = typeof window !== "undefined" ? (window.localStorage.getItem(STORE) ?? "") : ""; } catch { /* storage unavailable */ }
  const agent = active.find((a) => a.id === urlAgent) ?? active.find((a) => a.id === stored) ?? active[0];
  useEffect(() => {
    if (agent) try { window.localStorage.setItem(STORE, agent.id); } catch { /* convenience only */ }
  }, [agent]);

  const runs = useQuery({ queryKey: ["runs", "overview", agent?.id], enabled: !!agent, queryFn: () => listRuns({ agent_id: agent!.id, limit: 6 }), refetchOnWindowFocus: true });
  const latest = runs.data?.items?.find((r) => r.status !== "draft");
  const items = useQuery({ queryKey: ["run-items", latest?.id, "overview"], enabled: !!latest, queryFn: () => listRunItems(latest!.id) });
  const review = useQuery({ queryKey: ["calls", "needs-review"], queryFn: () => call(api.GET("/api/v1/calls", { params: { query: { needs_review: true, reviewed: false, limit: 5 } } })) });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => call(api.GET("/api/v1/metrics/summary")), refetchInterval: 15000 });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => call(api.GET("/api/v1/usage")) });
  const health = useQuery({ queryKey: ["health"], queryFn: () => call(api.GET("/api/v1/health")), refetchInterval: 15000 });

  if (agents.isError) return <><PageHeader eyebrow="Overview" title="Overview" /><ErrorPanel error={agents.error} what="agents" onRetry={() => void agents.refetch()} /></>;
  if (agents.isPending) return <OverviewSkeleton />;
  if (!agent)
    return (
      <>
        <PageHeader eyebrow="Overview" title="Add your first agent" description="An agent is the voice bot you want to test. Add one and run synthetic callers against it." actions={<LinkButton variant="primary" href="/agents/new">Add agent</LinkButton>} />
        <Panel bodyClassName="p-0"><EmptyState icon={Bot} title="No agents yet" body="Pareeksha scores calls to an agent, so start by adding yours." /></Panel>
      </>
    );

  const s = latest?.summary;
  const running = latest && ["queued", "running"].includes(latest.status);
  const failed = latest && s?.pass_rate != null && latest.progress.evaluated ? Math.round(latest.progress.evaluated * (1 - s.pass_rate)) : 0;
  const crit = s?.critical_failures ?? 0;
  const title = !latest ? "No runs yet for this agent" : running ? `Run is ${latest.progress.evaluated + latest.progress.error} of ${latest.progress.total} done` : latest.progress.evaluated === 0 ? "Latest run has no scored calls" : failed === 0 ? `Latest run passed all ${latest.progress.evaluated} calls` : `Latest run passed ${latest.progress.evaluated - failed} of ${latest.progress.evaluated} calls${crit ? `, ${crit} critical` : ""}`;
  const desc = latest ? `Run "${latest.name || latest.id.slice(0, 8)}" ${latest.finished_at ? `finished ${relativeTime(latest.finished_at)}` : `was created ${relativeTime(latest.created_at)}`}.${s?.needs_review ? ` ${s.needs_review} call${s.needs_review === 1 ? "" : "s"} need human review.` : ""}` : "A run sends synthetic callers to your agent and scores every call.";

  const worst = [...(items.data?.items ?? [])].filter((i) => i.overall_score != null).sort((a, b) => a.overall_score! - b.overall_score!).slice(0, 5);
  const lag = metrics.data ? Math.max(0, ...Object.values(metrics.data.consumer_lag)) : 0;
  const stale = metrics.dataUpdatedAt && now && now - metrics.dataUpdatedAt > 45000;
  const budget = usage.data?.budget_credits;

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="inline-flex items-center gap-3">
            <span>{agent.name}</span>
            {active.length > 1 && <FilterSelect label="Agent" value={agent.id} onChange={(v) => url.set({ agent: v })} options={active.map((a) => ({ value: a.id, label: a.name }))} />}
          </span>
        }
        title={title}
        description={desc}
        actions={<LinkButton variant="primary" href={`/runs/new?agent=${agent.id}`}><Play size={14} strokeWidth={1.6} aria-hidden />New run</LinkButton>}
      />
      <TileRow cols="grid-cols-2 min-[860px]:grid-cols-4">
        <StatTile href={latest ? `/runs/${latest.id}` : "/runs"} hero label={`Pass rate${running ? " so far" : ""}`} value={s?.pass_rate != null ? `${Math.round(s.pass_rate * 100)}%` : "-"} caption={latest ? `${latest.progress.evaluated} scored` : "no runs"} />
        <StatTile href={latest ? `/runs/${latest.id}?verdict=critical` : "/runs"} label="Critical failures" value={s?.critical_failures ?? "-"} threshold={s?.critical_failures == null ? null : s.critical_failures > 0 ? "fail" : "ok"} caption="target 0" />
        <StatTile href="/dlq" label="Open DLQ items" value={metrics.data?.dlq_open ?? "-"} threshold={metrics.data == null ? null : metrics.data.dlq_open > 0 ? "fail" : "ok"} caption="events that failed processing" />
        <StatTile label="Credits used" value={inr(usage.data?.credits_used)} caption={budget != null ? <span className="inline-flex items-center gap-2">of {inr(budget)} <Meter value={Math.min(100, ((usage.data?.credits_used ?? 0) / budget) * 100)} passLine={null} label="Budget used" /></span> : "no budget set"} />
      </TileRow>

      <div className="mb-6 grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
        <Panel title="Worst calls, latest run" aux={latest && <Link className="text-accent-fg underline-offset-2 hover:underline" href={`/runs/${latest.id}`}>Open run</Link>}>
          {!latest ? (
            <EmptyState icon={Play} title="No runs yet" body="A run sends synthetic callers to your agent." action={<LinkButton variant="primary" href={`/runs/new?agent=${agent.id}`}>Create run</LinkButton>} />
          ) : (
            <PanelBody q={items} rows={worst.length} empty="No scored calls in the latest run yet.">
              <ol className="flex flex-col divide-y divide-border">
                {worst.map((i) => (
                  <li key={i.id} className="flex items-center gap-3 py-2">
                    <ScoreChip score={i.overall_score} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm">{i.call_id ? <Link className="font-medium underline-offset-2 hover:underline" href={`/calls/${i.call_id}`}>{i.scenario}</Link> : i.scenario}</p>
                      <p className="truncate text-xs text-muted">{i.persona} · {i.noise_profile}</p>
                    </div>
                    <VerdictBadge verdict={verdictOf(i)} />
                  </li>
                ))}
              </ol>
            </PanelBody>
          )}
        </Panel>
        <Panel title="Platform health" aux={stale ? <span className="text-warn-fg">Last updated {relativeTime(new Date(metrics.dataUpdatedAt).toISOString())}</span> : undefined}>
          <PanelBody q={metrics} rows={1} empty="">
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted">API</dt>
              <dd><Status ok={health.data?.db === "ok"} label={health.data ? "ok" : "unknown"} /></dd>
              <dt className="text-muted">Database</dt>
              <dd><Status ok={health.data?.db === "ok"} label={health.data?.db ?? "unknown"} /></dd>
              <dt className="text-muted">Kafka</dt>
              <dd><Status ok={health.data?.kafka === "ok"} fail={health.data?.kafka !== "ok" && !!health.data} label={health.data?.kafka ?? "unknown"} /></dd>
              <dt className="text-muted">Outbox backlog</dt>
              <dd className="mono">{metrics.data?.outbox_backlog ?? "-"}</dd>
              {Object.entries(metrics.data?.consumer_lag ?? {}).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">Lag: <span className="mono">{k}</span></dt>
                  <dd className={v > 20 ? "mono text-warn-fg" : "mono"}>{v}</dd>
                </div>
              ))}
              {lag > 20 && <p className="col-span-2 text-xs text-warn-fg">A consumer is more than 20 events behind.</p>}
            </dl>
          </PanelBody>
        </Panel>
      </div>

      <div className="grid items-start gap-6 min-[1180px]:grid-cols-2">
        <Panel title="Recent runs" bodyClassName="p-0" aux={<Link className="text-accent-fg underline-offset-2 hover:underline" href="/runs">All runs</Link>}>
          <div className="p-4">
            <PanelBody q={runs} rows={runs.data?.items?.length ?? 0} empty="No runs yet.">
              <table className="rt">
                <caption className="sr-only">Recent runs</caption>
                <thead><tr><th scope="col">Name</th><th scope="col">Status</th><th scope="col">Pass rate</th><th scope="col">When</th></tr></thead>
                <tbody>
                  {runs.data?.items?.slice(0, 5).map((r) => (
                    <tr key={r.id}>
                      <td><Link className="font-medium underline-offset-2 hover:underline" href={`/runs/${r.id}`}>{r.name || r.id.slice(0, 8)}</Link></td>
                      <td data-label="Status"><StatusPill status={r.status} /></td>
                      <td data-label="Pass rate" className="mono">{r.summary?.pass_rate != null ? `${Math.round(r.summary.pass_rate * 100)}%` : "-"}</td>
                      <td data-label="When" className="text-muted"><time dateTime={r.created_at}>{relativeTime(r.created_at)}</time></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </PanelBody>
          </div>
        </Panel>
        <Panel title="Needs human review" aux={<Link className="text-accent-fg underline-offset-2 hover:underline" href="/calibration">Calibration</Link>}>
          <PanelBody q={review} rows={review.data?.items?.length ?? 0} empty="No calls are waiting for review.">
            <ul className="flex flex-col divide-y divide-border">
              {review.data?.items?.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2 py-2">
                  <ScoreChip score={c.overall_score} />
                  <Link className="mono text-sm underline-offset-2 hover:underline" href={`/calls/${c.id}`}>{c.id.slice(0, 8)}</Link>
                  <FlagChip iconOnly reasons={c.review_reasons} />
                  {(c.review_reasons ?? []).slice(0, 2).map((x) => <Chip key={x} mono>{x}</Chip>)}
                  {(c.review_reasons ?? []).length > 2 && <span className="mono text-xs text-muted" title={(c.review_reasons ?? []).slice(2).join(", ")}>+{(c.review_reasons ?? []).length - 2}</span>}
                </li>
              ))}
            </ul>
          </PanelBody>
        </Panel>
      </div>
    </>
  );
}

function Status({ ok, label, fail }: { ok: boolean; label: string; fail?: boolean }) {
  return (
    <span className={fail ? "inline-flex items-center gap-1.5 text-fail-fg" : "inline-flex items-center gap-1.5"}>
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-pass" : fail ? "bg-fail" : "bg-border-strong"}`} aria-hidden />
      <span className="mono">{label}</span>
    </span>
  );
}
