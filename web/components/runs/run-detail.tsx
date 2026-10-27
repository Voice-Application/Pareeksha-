"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { DataTable, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { FilterSelect, Segmented } from "@/components/ui/field";
import { ConfirmDialog } from "@/components/ui/overlay";
import { ErrorPanel, PageError, Skeleton, Strip, TableSkeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { useNow } from "@/lib/hooks/use-now";
import { relativeTime } from "@/lib/format";
import type { RunItem, RunSummary } from "@/lib/api/runs";
import { FlagChip, ProgressBar, ScoreChip, StatTile, StatusPill, TagChip, TileRow, VerdictBadge, overallStep, verdictOf, type Threshold } from "@/components/ui/measure";
import { Heatmap, HeatmapLegend } from "./heatmap";
import { LiveIndicator } from "./live-indicator";
import { useRunLive } from "./use-run-live";

const ACTIVE = new Set(["queued", "running", "draft"]);

function Histogram({ bins }: { bins: number[] }) {
  const max = Math.max(1, ...bins);
  const H = 120;
  const W = 300;
  const bw = W / 10;
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H + 22}`} className="w-full" role="img" aria-label={`Score distribution: ${bins.map((n, i) => `${i * 10}-${i === 9 ? 100 : i * 10 + 9}: ${n}`).join(", ")}`}>
        {[0, 0.5, 1].map((t) => (
          <line key={t} x1="0" x2={W} y1={H - t * (H - 14)} y2={H - t * (H - 14)} stroke="var(--grid)" strokeWidth="1" />
        ))}
        {bins.map((n, i) => {
          const h = (n / max) * (H - 14);
          const step = overallStep(i * 10 + 5);
          return (
            <g key={i}>
              {n > 0 && <rect x={i * bw + 2} y={H - h} width={bw - 4} height={h} rx="2" fill={`var(--score-${step})`} />}
              {n > 0 && (
                <text x={i * bw + bw / 2} y={H - h - 3} textAnchor="middle" className="mono" fontSize="9" fill="var(--fg-muted)">
                  {n}
                </text>
              )}
              <text x={i * bw + bw / 2} y={H + 12} textAnchor="middle" className="mono" fontSize="8" fill="var(--fg-subtle)">
                {i * 10}
              </text>
            </g>
          );
        })}
        <line x1={8 * bw} x2={8 * bw} y1="0" y2={H} stroke="var(--fg)" strokeWidth="1" strokeDasharray="3 3" />
        <text x={8 * bw - 3} y="9" textAnchor="end" fontSize="9" fill="var(--fg-muted)" className="mono">
          pass 80
        </text>
      </svg>
    </figure>
  );
}

/** While a run is in flight the server summary is still empty; tiles show values computed from the evaluated items ("so far"). */
function provisional(all: RunItem[], base: RunSummary | undefined): RunSummary | undefined {
  const done = all.filter((i) => i.overall_score != null);
  if (!done.length) return base;
  const scores = done.map((i) => i.overall_score as number);
  return {
    ...base,
    pass_rate: done.filter((i) => i.passed).length / done.length,
    critical_failures: done.filter((i) => i.critical_failure).length,
    score_mean: scores.reduce((a, b) => a + b, 0) / scores.length,
    score_distribution: Array.from({ length: 10 }, (_, b) => scores.filter((x) => Math.min(Math.floor(x / 10), 9) === b).length),
  };
}

function latencyThreshold(ms: number | null | undefined, target: number): Threshold {
  if (ms == null) return null;
  return ms <= target ? "ok" : ms <= target * 1.25 ? "warn" : "fail";
}
const sec = (ms: number | null | undefined) => (ms == null ? "-" : ms < 10000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 1000)} s`);

export function RunDetailSkeleton() {
  return (
    <>
      <PageHeader eyebrow="Run" title="" description={<Skeleton className="h-4 w-72" />} />
      <TileRow>{Array.from({ length: 6 }, (_, i) => <div key={i} className="px-4 py-3"><Skeleton className="h-3 w-16" /><Skeleton className="mt-2 h-6 w-16" /></div>)}</TileRow>
      <Panel title="Matrix"><div role="status" aria-label="Loading" aria-busy="true" className="grid grid-cols-4 gap-0.5">{Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div></Panel>
    </>
  );
}

export function RunDetail({ runId }: { runId: string }) {
  const { run, items, live, updatedAt, flash } = useRunLive(runId);
  const url = useUrlState();
  const qc = useQueryClient();
  const { toast } = useToast();
  const now = useNow();
  const [line, setLine] = useState("all");
  const [sortBy, setSortBy] = useState<"worst" | "name">("worst");
  const [confirmCancel, setConfirmCancel] = useState(false);

  const agent = useQuery({ queryKey: ["agent", run.data?.agent_id], enabled: !!run.data, queryFn: () => call(api.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: run.data!.agent_id } } })) });
  const calls = useQuery({
    queryKey: ["run-calls", runId, run.data?.progress.evaluated],
    enabled: !!run.data && run.data.progress.evaluated > 0,
    queryFn: () => call(api.GET("/api/v1/calls", { params: { query: { run_id: runId, limit: 200 } } })),
  });
  const cancel = useMutation({
    mutationFn: () => call(api.POST("/api/v1/runs/{run_id}/cancel", { params: { path: { run_id: runId } } })),
    onSuccess: () => {
      setConfirmCancel(false);
      toast("Cancelling the run.");
      void qc.invalidateQueries({ queryKey: ["run", runId] });
    },
    onError: (e) => {
      setConfirmCancel(false);
      toast(`Could not cancel: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error" });
    },
  });

  const lines = useMemo(() => [...new Set((items.data ?? []).map((i) => i.noise_profile))], [items.data]);
  const callInfo = useMemo(() => new Map((calls.data?.items ?? []).map((c) => [c.id, c])), [calls.data]);

  if (run.isError) return <PageError error={run.error} onRetry={() => void run.refetch()} backHref="/runs" backLabel="Back to runs" />;
  if (run.isPending) return <RunDetailSkeleton />;

  const r = run.data;
  const s = r.summary?.pass_rate != null ? r.summary : provisional(items.data ?? [], r.summary);
  const p = r.progress;
  const total = p.total;
  const done = p.evaluated + p.error;
  const running = ACTIVE.has(r.status);
  const failed = s?.pass_rate != null && p.evaluated ? Math.round(p.evaluated * (1 - s.pass_rate)) : 0;
  const crit = s?.critical_failures ?? 0;
  const title =
    r.status === "queued" && !total ? "Run queued"
    : running ? `Run is ${done} of ${total} done`
    : r.status === "cancelled" ? `Run cancelled after ${done} of ${total} calls`
    : r.status === "failed" ? "Run failed before finishing"
    : p.evaluated === 0 ? "No calls were scored"
    : failed === 0 ? `All ${p.evaluated} calls passed`
    : `${failed} of ${p.evaluated} calls failed${crit ? `, ${crit} critical` : ""}`;
  const tops = (s?.top_failure_types ?? []).map((t) => [String(t[0]), Number(t[1])] as const);
  const top = tops[0];
  const desc = running
    ? "Results appear as each call is evaluated."
    : [r.finished_at ? `Finished ${relativeTime(r.finished_at)}.` : "", s?.needs_review ? `${s.needs_review} call${s.needs_review === 1 ? "" : "s"} need human review.` : "", top ? `Top failure: ${top[0]} x${top[1]}.` : ""].filter(Boolean).join(" ");

  const all = items.data ?? [];
  const stale = !running ? false : now - updatedAt > 15000;
  const errored = p.error;
  const bins = s?.score_distribution?.length === 10 ? s.score_distribution : new Array(10).fill(0);

  const sorters: Sorters<RunItem> = {
    scenario: (i) => i.scenario.toLowerCase(),
    persona: (i) => i.persona.toLowerCase(),
    line: (i) => i.noise_profile,
    status: (i) => i.status,
    score: (i) => i.overall_score ?? null,
  };
  const sort = parseSort(url.get("sort")) ?? { key: "score", dir: "asc" as const };
  const fv = url.get("verdict");
  const ff = url.get("flag");
  const fs = url.get("status");
  const visible = sortRows(
    all.filter((i) => {
      const c = i.call_id ? callInfo.get(i.call_id) : undefined;
      if (fv && verdictOf(i) !== fv) return false;
      if (ff === "review" && !c?.needs_human_review) return false;
      if (fs && i.status !== fs) return false;
      return true;
    }),
    sorters,
    sort,
  );
  const columns: Column<RunItem>[] = [
    { key: "scenario", header: "Scenario", sortable: true, cell: (i) => (i.call_id ? <Link className="font-medium underline-offset-2 hover:underline" href={`/calls/${i.call_id}`}>{i.scenario}</Link> : i.scenario) },
    { key: "persona", header: "Persona", sortable: true, cell: (i) => i.persona },
    { key: "line", header: "Line", sortable: true, hidePhone: true, cell: (i) => i.noise_profile },
    { key: "status", header: "Status", sortable: true, cell: (i) => <StatusPill status={i.status} /> },
    { key: "score", header: "Score", sortable: true, cell: (i) => <ScoreChip score={i.overall_score} /> },
    { key: "verdict", header: "Verdict", cell: (i) => <VerdictBadge verdict={verdictOf(i)} /> },
    {
      key: "flag",
      header: "Flag",
      hidePhone: true,
      cell: (i) => {
        const c = i.call_id ? callInfo.get(i.call_id) : undefined;
        return c?.needs_human_review ? <FlagChip iconOnly reasons={c.review_reasons} /> : <span className="text-subtle">-</span>;
      },
    },
    {
      key: "tags",
      header: "Tags",
      hidePhone: true,
      cell: (i) => {
        const c = i.call_id ? callInfo.get(i.call_id) : undefined;
        const t = c?.failure_types ?? [];
        return t.length ? <span className="flex flex-wrap gap-1"><TagChip key={t[0]} tag={t[0]} />{t.length > 1 && <span className="mono text-xs text-muted" title={t.slice(1).join(", ")}>+{t.length - 1}</span>}</span> : <span className="text-subtle">-</span>;
      },
    },
    { key: "dur", header: "Duration", mono: true, hidePhone: true, cell: (i) => { const d = i.call_id ? callInfo.get(i.call_id)?.duration_ms : null; return d ? `${Math.floor(d / 60000)}:${String(Math.floor((d % 60000) / 1000)).padStart(2, "0")}` : <span className="text-subtle">-</span>; } },
  ];

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span>Run</span>
            <span className="normal-case">{r.name || r.id.slice(0, 8)}</span>
            <span aria-hidden>|</span>
            <span className="normal-case">{agent.data?.name ?? "agent"}</span>
            <span aria-hidden>|</span>
            <span className="normal-case">{r.kind}</span>
            <LiveIndicator state={live} />
          </span>
        }
        title={title}
        description={desc}
        actions={
          <>
            {running && <Button onClick={() => setConfirmCancel(true)}>Cancel</Button>}
            {!running && <LinkButton href={`/runs/new?agent=${r.agent_id}`}>Re-run</LinkButton>}
            {!running && <LinkButton variant="primary" href={`/runs/compare?head=${r.id}`}>Compare</LinkButton>}
          </>
        }
      />
      {running && (
        <div className="mb-6 flex items-center gap-3 rounded-md border border-border bg-surface px-4 py-2">
          <span className="text-sm text-muted">{r.status === "queued" && done === 0 ? "Waiting for the planner" : "Progress"}</span>
          <div className="flex-1"><ProgressBar done={done} total={total} label="Run progress" /></div>
          {stale && <span className="text-xs text-warn-fg">Updated {relativeTime(new Date(updatedAt).toISOString())}</span>}
        </div>
      )}
      {r.status === "failed" && <div className="mb-6"><Strip tone="error">The run did not finish. The planner or every call errored. Re-run it, or open the DLQ page if events are stuck.</Strip></div>}
      {!running && r.status !== "failed" && p.evaluated > 0 && failed === 0 && crit === 0 && (
        <p className="mb-6 rounded-md border border-border bg-pass-tint px-4 py-2 text-sm text-pass-fg">No failures. {p.evaluated} of {p.evaluated} passed.</p>
      )}
      <TileRow>
        <StatTile hero label={`Pass rate${running ? " so far" : ""}`} value={s?.pass_rate != null ? `${Math.round(s.pass_rate * 100)}%` : "-"} caption={p.evaluated ? `${p.evaluated} scored` : undefined} />
        <StatTile label="Critical" value={s?.critical_failures ?? "-"} threshold={s?.critical_failures == null ? null : s.critical_failures > 0 ? "fail" : "ok"} caption="target 0" />
        <StatTile label="Mean score" value={s?.score_mean != null ? s.score_mean.toFixed(1) : "-"} caption="pass line 80" />
        <StatTile label="Latency p50" value={sec(s?.latency_p50_ms)} threshold={latencyThreshold(s?.latency_p50_ms, 1000)} caption="target under 1.0 s" />
        <StatTile label="Latency p95" value={sec(s?.latency_p95_ms)} threshold={latencyThreshold(s?.latency_p95_ms, 2000)} caption="target under 2.0 s" />
        <StatTile label="Barge-in honoured" value={s?.barge_in_honoured_rate != null ? `${Math.round(s.barge_in_honoured_rate * 100)}%` : "-"} caption="target at least 90%" threshold={s?.barge_in_honoured_rate == null ? null : s.barge_in_honoured_rate >= 0.9 ? "ok" : "fail"} />
      </TileRow>
      {errored > 0 && (
        <p className="-mt-3 mb-6 text-sm text-muted">
          {errored} call{errored === 1 ? "" : "s"} errored and {errored === 1 ? "is" : "are"} not scored.{" "}
          <button type="button" className="text-accent-fg underline" onClick={() => url.set({ status: "error" })}>Show them</button>
        </p>
      )}

      <div className="mb-6 grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
        <Panel
          title="Matrix"
          aux={
            <>
              <FilterSelect label="Line" value={line} onChange={setLine} options={[{ value: "all", label: "All lines" }, ...lines.map((l) => ({ value: l, label: l }))]} />
              <Segmented hideLabel label="Sort" value={sortBy} onChange={setSortBy} options={[{ value: "worst", label: "Worst first" }, { value: "name", label: "Name" }]} />
            </>
          }
        >
          {items.isError ? (
            <ErrorPanel error={items.error} what="items" onRetry={() => void items.refetch()} />
          ) : items.isPending ? (
            <div role="status" aria-label="Loading" aria-busy="true" className="grid grid-cols-4 gap-0.5">{Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
          ) : all.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-muted"><CircleAlert size={16} strokeWidth={1.6} aria-hidden />This run has no calls yet. {r.status === "queued" ? "Waiting for the planner." : "The matrix was empty after filtering."}</p>
          ) : (
            <>
              <Heatmap items={all} line={line} sortBy={sortBy} flashIds={flash} runKey={runId} />
              <HeatmapLegend />
            </>
          )}
        </Panel>
        <div className="flex flex-col gap-6">
          <Panel title="Score distribution" aux={<span className="mono text-xs">{p.evaluated} calls</span>}>
            {p.evaluated ? <Histogram bins={bins} /> : <p className="text-sm text-subtle">No scores yet.</p>}
          </Panel>
          <Panel title="Top failure types">
            {tops.length ? (
              <ul className="flex flex-col gap-2">
                {tops.slice(0, 6).map(([tag, n]) => (
                  <li key={tag} className="flex items-center gap-3">
                    <span className="w-48 shrink-0"><TagChip tag={tag} /></span>
                    <span className="h-1.5 flex-1 rounded-xs bg-sunken"><span className="block h-full rounded-xs bg-series-1" style={{ width: `${(n / tops[0][1]) * 100}%`, background: "var(--series-1)" }} /></span>
                    <span className="mono w-6 text-right text-sm">{n}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-subtle">No failure tags.</p>
            )}
          </Panel>
        </div>
      </div>

      <Panel title="Calls" bodyClassName="p-0" aux={<span className="mono text-xs">{visible.length} of {all.length}</span>}>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <FilterSelect label="Verdict" value={fv} onChange={(v) => url.set({ verdict: v })} options={[{ value: "", label: "All verdicts" }, { value: "pass", label: "Pass" }, { value: "fail", label: "Fail" }, { value: "critical", label: "Critical" }]} />
          <FilterSelect label="Flag" value={ff} onChange={(v) => url.set({ flag: v })} options={[{ value: "", label: "Any flag" }, { value: "review", label: "Needs human review" }]} />
          <FilterSelect label="Status" value={fs} onChange={(v) => url.set({ status: v })} options={[{ value: "", label: "All statuses" }, ...["queued", "in_progress", "evaluated", "judge_error", "error", "cancelled"].map((x) => ({ value: x, label: x.replace("_", " ") }))]} />
          {(fv || ff || fs) && <Button variant="ghost" onClick={() => url.set({ verdict: null, flag: null, status: null })}>Clear</Button>}
        </div>
        {items.isPending ? (
          <TableSkeleton rows={8} label="Loading calls" />
        ) : visible.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted">{all.length ? "No calls match these filters." : "No calls yet."}</p>
        ) : (
          <DataTable caption="Calls in this run" columns={columns} rows={visible} rowKey={(i) => i.id} sort={sort} onSort={(n) => url.set({ sort: n })} />
        )}
      </Panel>
      <ConfirmDialog open={confirmCancel} onClose={() => setConfirmCancel(false)} title="Cancel run" body="In-flight calls will hang up cleanly. Cancel run?" confirmLabel="Cancel run" busy={cancel.isPending} onConfirm={() => cancel.mutate()} />
    </>
  );
}
