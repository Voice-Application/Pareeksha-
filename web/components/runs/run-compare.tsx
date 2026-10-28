"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowLeftRight, ArrowUp, CircleCheck, CircleX, GitCompare, Minus, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { getCall, RUBRIC } from "@/lib/api/calls";
import { getRun, listRunItems, listRuns, type Run, type RunItem } from "@/lib/api/runs";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { SelectField } from "@/components/ui/field";
import { EmptyState, ErrorPanel, PageError, Skeleton, Strip, TableSkeleton } from "@/components/ui/states";
import { StatTile, TileRow, fmtScore, overallStep, stepStyle, type Threshold } from "@/components/ui/measure";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { cn } from "@/lib/utils";
import { cellKey, callByCell, dimensionMeans, groupOf, listDiff, sortCells, type Compared, type Group } from "./compare-diff";

const ACTIVE = new Set(["queued", "running", "draft"]);
const POLL = 5000;
const DIM_CALL_CAP = 60;
const GROUP_LABEL: Record<Group, string> = { newly: "Newly failing", regressed: "Regressed", improved: "Improved", unchanged: "Unchanged", partial: "Not comparable" };

const callIds = (items: RunItem[] | undefined) => (items ?? []).filter((i) => i.call_id && i.overall_score != null).slice(0, DIM_CALL_CAP).map((i) => i.call_id as string);
const signed = (n: number, digits = 0) => `${n > 0 ? "+" : n < 0 ? "-" : ""}${Math.abs(n).toFixed(digits)}`;
const pct = (x: number | null | undefined) => (x == null ? null : Math.round(x * 100));
const sec = (ms: number) => (ms < 10000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 1000)} s`);
const runLabel = (r: Run) => r.name || r.id.slice(0, 8);
const dateOf = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export function RunCompareSkeleton() {
  return (
    <>
      <PageHeader eyebrow="Run compare" title="" description={<Skeleton className="h-4 w-72" />} />
      <TileRow cols="grid-cols-2 min-[860px]:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <div key={i} className="px-4 py-3"><Skeleton className="h-3 w-16" /><Skeleton className="mt-2 h-6 w-16" /></div>)}</TileRow>
      <Panel title="Changed cells" bodyClassName="p-0"><TableSkeleton rows={5} label="Loading comparison" /></Panel>
    </>
  );
}

type Verdict = { threshold: Threshold; word: string };
/** Good/bad direction is stated in words and by the check or cross icon, never by arrow colour alone. */
function direction(delta: number | null, goodWhenUp: boolean, unit: string): Verdict {
  if (delta == null) return { threshold: null, word: "no comparison" };
  if (delta === 0) return { threshold: null, word: "no change" };
  const up = delta > 0;
  return { threshold: up === goodWhenUp ? "ok" : "fail", word: `${up ? "up" : "down"} ${Math.abs(delta)} ${Math.abs(delta) === 1 ? unit.replace(/s$/, "") : unit}, ${up === goodWhenUp ? "better" : "worse"}` };
}

function DeltaTile({ label, base, head, delta, goodWhenUp, unit, digits = 0, show }: { label: string; base: string; head: string; delta: number | null; goodWhenUp: boolean; unit: string; digits?: number; show?: string }) {
  const v = direction(delta == null ? null : Number(delta.toFixed(digits)), goodWhenUp, unit);
  const Arrow = delta == null || delta === 0 ? Minus : delta > 0 ? ArrowUp : ArrowDown;
  return (
    <StatTile
      label={label}
      threshold={v.threshold}
      value={<><Arrow size={16} strokeWidth={1.6} aria-hidden />{delta == null ? head : show ?? `${signed(delta, digits)} ${unit}`}</>}
      caption={<>{v.word}. {base} to {head}.</>}
    />
  );
}

function RunPicker({ label, value, runs, onChange, exclude }: { label: string; value: string; runs: Run[]; onChange: (id: string) => void; exclude?: string }) {
  return (
    <SelectField label={label} value={value} onChange={(e) => onChange(e.target.value)} fieldClassName="min-w-[16rem] flex-1">
      <option value="">Choose a run</option>
      {runs.map((r) => (
        <option key={r.id} value={r.id} disabled={r.id === exclude && r.id !== value}>
          {runLabel(r)} - {dateOf(r.created_at)}{r.summary?.pass_rate != null ? ` - ${pct(r.summary.pass_rate)}% pass` : ` - ${r.status}`}
        </option>
      ))}
    </SelectField>
  );
}

export function RunCompare() {
  const url = useUrlState();
  const base = url.get("base");
  const head = url.get("head");
  const [draft, setDraft] = useState<{ base: string; head: string }>({ base, head });
  const ready = !!base && !!head;

  const list = useQuery({ queryKey: ["runs-pick"], queryFn: () => listRuns({ limit: 100 }) });
  const runQ = useQueries({ queries: [base, head].map((id) => ({ queryKey: ["compare-run", id], enabled: !!id, queryFn: () => getRun(id), refetchInterval: (q: { state: { data?: Run } }) => (q.state.data && ACTIVE.has(q.state.data.status) ? POLL : false) })) });
  const [baseRun, headRun] = runQ;
  const polling = [baseRun.data, headRun.data].some((r) => r && ACTIVE.has(r.status));
  const bothOk = ready && baseRun.isSuccess && headRun.isSuccess;
  const cmp = useQuery({
    queryKey: ["compare", base, head, baseRun.data?.progress.evaluated, headRun.data?.progress.evaluated],
    enabled: bothOk && base !== head,
    queryFn: () => call(api.GET("/api/v1/runs/compare", { params: { query: { base, head } } })),
    refetchInterval: polling ? POLL : false,
  });
  const itemQ = useQueries({ queries: [base, head].map((id) => ({ queryKey: ["compare-items", id, id === base ? baseRun.data?.progress.evaluated : headRun.data?.progress.evaluated], enabled: bothOk, queryFn: () => listRunItems(id) })) });
  const baseItems = itemQ[0].data?.items;
  const headItems = itemQ[1].data?.items;
  const agents = useQueries({ queries: [baseRun.data?.agent_id, headRun.data?.agent_id].map((id) => ({ queryKey: ["agent", id], enabled: !!id, queryFn: () => call(api.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: id as string } } })) })) });

  // Per-dimension means come from the evaluations of each run's calls: the compare endpoint only carries overall scores.
  const baseCalls = useMemo(() => callIds(baseItems), [baseItems]);
  const headCalls = useMemo(() => callIds(headItems), [headItems]);
  const dimQ = useQueries({ queries: [...baseCalls, ...headCalls].map((id) => ({ queryKey: ["compare-call", id], queryFn: () => getCall(id), staleTime: 60_000 })) });
  const dimsLoading = dimQ.some((q) => q.isPending);
  const dims = useMemo(() => {
    const evs = dimQ.map((q) => q.data?.evaluation);
    const pick = (from: number, n: number) => dimensionMeans(evs.slice(from, from + n).filter((e): e is NonNullable<typeof e> => !!e));
    return { base: pick(0, baseCalls.length), head: pick(baseCalls.length, headCalls.length) };
  }, [dimQ, baseCalls.length, headCalls.length]);

  const baseCall = useMemo(() => callByCell(baseItems), [baseItems]);
  const headCall = useMemo(() => callByCell(headItems), [headItems]);

  const runs = useMemo(() => {
    const seen = new Map((list.data?.items ?? []).map((r) => [r.id, r as Run]));
    for (const r of [baseRun.data, headRun.data]) if (r && !seen.has(r.id)) seen.set(r.id, r);
    return [...seen.values()];
  }, [list.data, baseRun.data, headRun.data]);

  const setPick = (which: "base" | "head", id: string) => {
    setDraft((d) => ({ ...d, [which]: id }));
    if (ready || (which === "base" ? head : base)) url.set({ [which]: id || null });
  };
  const swap = () => url.set({ base: head, head: base });

  const pickers = (
    <div className="mb-6 flex flex-wrap items-end gap-3">
      <RunPicker label="Base run" value={ready ? base : draft.base} runs={runs} exclude={ready ? head : draft.head} onChange={(id) => setPick("base", id)} />
      <Button aria-label="Swap base and head" icon disabled={!ready} onClick={swap}><ArrowLeftRight size={16} strokeWidth={1.6} aria-hidden /></Button>
      <RunPicker label="Head run" value={ready ? head : draft.head} runs={runs} exclude={ready ? base : draft.base} onChange={(id) => setPick("head", id)} />
      {!ready && <Button variant="primary" disabled={!draft.base || !draft.head || draft.base === draft.head} onClick={() => url.set({ base: draft.base, head: draft.head })}>Compare</Button>}
    </div>
  );

  if (!ready) {
    return (
      <>
        <PageHeader eyebrow="Run compare" title="Choose two runs to compare" description="Pick a base run and a head run. Regressions are listed first." />
        {list.isError && <div className="mb-6"><ErrorPanel error={list.error} what="runs" onRetry={() => void list.refetch()} /></div>}
        {pickers}
        {list.isSuccess && runs.length < 2 && <EmptyState icon={GitCompare} title="Not enough runs to compare" body="Comparing needs two runs of the same agent. Create another run first." action={<LinkButton variant="primary" href="/runs/new">New run</LinkButton>} />}
      </>
    );
  }

  const notFound = runQ.map((q, i) => ({ q, id: i === 0 ? base : head })).find((x) => x.q.isError);
  if (notFound) return <PageError error={notFound.q.error} onRetry={() => void notFound.q.refetch()} backHref="/runs" backLabel="Back to runs" />;
  if (!baseRun.data || !headRun.data) return <RunCompareSkeleton />;

  const b = baseRun.data;
  const h = headRun.data;
  const same = base === head;
  const sameAgent = b.agent_id === h.agent_id;
  const bs = b.summary;
  const hs = h.summary;
  const cells = (cmp.data?.cells ?? []) as Compared[];
  const counts = cmp.data?.summary;
  const sorted = sortCells(cells);
  const changed = sorted.filter((c) => !["unchanged", "partial"].includes(groupOf(c)));
  const unchanged = sorted.filter((c) => groupOf(c) === "unchanged");
  const partial = sorted.filter((c) => groupOf(c) === "partial");
  const overlap = cells.filter((c) => c.delta != null).length;
  const newly = sorted.filter((c) => c.newly_failing);

  const title = same ? "Base and head are the same run"
    : cmp.isPending ? ""
    : cmp.isError ? "Comparison unavailable"
    : overlap === 0 ? "No overlapping cells"
    : counts && counts.regressed === 0 && counts.improved === 0 ? "No differences"
    : `${counts?.regressed ?? 0} cells regressed, ${counts?.improved ?? 0} improved, ${counts?.unchanged ?? 0} unchanged`;
  const bp = pct(bs?.pass_rate);
  const hp = pct(hs?.pass_rate);
  const first = newly[0];
  const description = same ? undefined : [
    bp != null && hp != null ? `Pass rate ${bp}% to ${hp}%.` : "",
    first ? `Newly failing: ${first.scenario} x ${first.persona} (${fmtScore(first.base_score)} to ${fmtScore(first.head_score)})${newly.length > 1 ? ` and ${newly.length - 1} more` : ""}.` : "",
  ].filter(Boolean).join(" ") || undefined;

  const eyebrow = (
    <span className="inline-flex flex-wrap items-center gap-x-2">
      <span>Base</span><span className="normal-case">{runLabel(b)} ({dateOf(b.created_at)})</span>
      <span aria-hidden>to</span>
      <span>Head</span><span className="normal-case">{runLabel(h)} ({dateOf(h.created_at)})</span>
    </span>
  );

  const link = (kind: "Base" | "Head", c: Compared) => {
    const id = (kind === "Base" ? baseCall : headCall).get(cellKey(c.scenario, c.persona, c.profile));
    return id ? <Link className="text-accent-fg underline underline-offset-2" href={`/calls/${id}`}>{kind} call</Link> : <span className="text-subtle">-</span>;
  };
  const columns: Column<Compared>[] = [
    { key: "scenario", header: "Scenario", className: "min-w-[12rem]", cell: (c) => <span className="font-medium">{c.scenario}</span> },
    { key: "persona", header: "Persona", cell: (c) => c.persona },
    { key: "line", header: "Line", hidePhone: true, cell: (c) => c.profile },
    { key: "base", header: "Base", mono: true, cell: (c) => fmtScore(c.base_score) },
    { key: "head", header: "Head", mono: true, cell: (c) => fmtScore(c.head_score) },
    { key: "delta", header: "Delta", cell: (c) => <DeltaBar delta={c.delta} /> },
    { key: "status", header: "Status", cell: (c) => <StatusLabel c={c} /> },
    { key: "base_call", header: "Base call", hidePhone: true, cell: (c) => link("Base", c) },
    { key: "head_call", header: "Head call", hidePhone: true, cell: (c) => link("Head", c) },
  ];
  const noSort = () => undefined;
  const table = (rows: Compared[], caption: string) => <DataTable caption={caption} columns={columns} rows={rows} rowKey={(c) => cellKey(c.scenario, c.persona, c.profile)} sort={null} onSort={noSort} />;

  return (
    <>
      <PageHeader eyebrow={eyebrow} title={title} description={description} actions={<>
        <LinkButton href={`/runs/${h.id}`}>Open head run</LinkButton>
      </>} />
      {pickers}
      <div className="mb-6 flex flex-col gap-2">
        {same && <Strip tone="warn">Base and head are the same run. Choose two different runs.</Strip>}
        {!same && !sameAgent && <Strip tone="warn">These runs used different agents. Differences may not come from a prompt change.</Strip>}
        {ACTIVE.has(h.status) && <Strip tone="warn">Head is still running. Results update when it finishes.</Strip>}
        {ACTIVE.has(b.status) && <Strip tone="warn">Base is still running. Results update when it finishes.</Strip>}
      </div>
      <TileRow cols="grid-cols-2 min-[860px]:grid-cols-4">
        <DeltaTile label="Pass rate" base={bp != null ? `${bp}%` : "-"} head={hp != null ? `${hp}%` : "-"} delta={bp != null && hp != null ? hp - bp : null} goodWhenUp unit="points" />
        <DeltaTile label="Critical" base={String(bs?.critical_failures ?? "-")} head={String(hs?.critical_failures ?? "-")} delta={bs?.critical_failures != null && hs?.critical_failures != null ? hs.critical_failures - bs.critical_failures : null} goodWhenUp={false} unit="failures" />
        <DeltaTile label="Mean score" base={bs?.score_mean != null ? bs.score_mean.toFixed(1) : "-"} head={hs?.score_mean != null ? hs.score_mean.toFixed(1) : "-"} delta={bs?.score_mean != null && hs?.score_mean != null ? hs.score_mean - bs.score_mean : null} goodWhenUp unit="points" digits={1} />
        <DeltaTile label="Latency p95" base={bs?.latency_p95_ms != null ? sec(bs.latency_p95_ms) : "not measured"} head={hs?.latency_p95_ms != null ? sec(hs.latency_p95_ms) : "not measured"} delta={bs?.latency_p95_ms != null && hs?.latency_p95_ms != null ? (hs.latency_p95_ms - bs.latency_p95_ms) / 1000 : null} goodWhenUp={false} unit="s" digits={1} show={bs?.latency_p95_ms != null && hs?.latency_p95_ms != null ? `${signed((hs.latency_p95_ms - bs.latency_p95_ms) / 1000, 1)} s` : undefined} />
      </TileRow>

      {!same && cmp.isError && <div className="mb-6"><ErrorPanel error={cmp.error} what="the comparison" onRetry={() => void cmp.refetch()} /></div>}
      {!same && !cmp.isError && (
        <>
          <Panel title="Changed cells" className="mb-6" bodyClassName="p-0" aux={<span className="mono text-xs">{changed.length} changed</span>}>
            {cmp.isPending ? <TableSkeleton rows={5} label="Loading comparison" />
              : overlap === 0 ? <EmptyState icon={GitCompare} title="These runs share no scenario, persona and line combination" body="Re-run with the same matrix to compare them cell by cell." action={<LinkButton href={`/runs/new?agent=${h.agent_id}`}>New run</LinkButton>} />
              : changed.length === 0 ? <p className="p-6 text-center text-sm text-muted">No cell changed score between these runs.</p>
              : table(changed, "Changed cells, regressions first")}
            {unchanged.length > 0 && (
              <details className="border-t border-border">
                <summary className="cursor-pointer px-4 py-3 text-sm text-muted">{unchanged.length} unchanged</summary>
                {table(unchanged, "Unchanged cells")}
              </details>
            )}
            {partial.length > 0 && (
              <details className="border-t border-border">
                <summary className="cursor-pointer px-4 py-3 text-sm text-muted">{partial.length} not comparable (scored in only one run)</summary>
                {table(partial, "Cells scored in only one run")}
              </details>
            )}
          </Panel>

          <div className="mb-6 grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
            <Panel title="Diff heatmap" aux={<span className="text-xs">Head score, signed delta</span>}>
              {cmp.isPending ? <Skeleton className="h-32" /> : overlap === 0 ? <p className="text-sm text-muted">Nothing to draw: no shared cells.</p> : <DiffHeatmap cells={sorted} headCall={headCall} />}
            </Panel>
            <div className="flex flex-col gap-6">
              <Panel title="Dimensions" aux={<span className="mono text-xs">mean 0-4</span>}>
                <DimensionDeltas base={dims.base} head={dims.head} loading={dimsLoading || itemQ.some((q) => q.isPending)} failed={dimQ.some((q) => q.isError)} />
              </Panel>
              <Panel title="What changed in the agent">
                <AgentDiff same={sameAgent} base={agents[0].data} head={agents[1].data} loading={agents.some((a) => a.isPending)} />
              </Panel>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function StatusLabel({ c }: { c: Compared }) {
  const g = groupOf(c);
  const Icon = g === "newly" || g === "regressed" ? CircleX : g === "improved" ? CircleCheck : Minus;
  const tone = g === "newly" || g === "regressed" ? "text-fail-fg" : g === "improved" ? "text-pass-fg" : "text-muted";
  const why = g === "partial" ? (c.base_score == null && c.head_score == null ? "not scored" : c.base_score == null ? "only scored in head" : "only scored in base") : GROUP_LABEL[g].toLowerCase();
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", tone)}>
      <Icon size={14} strokeWidth={1.6} aria-hidden />{why}
    </span>
  );
}

/** 64px diverging bar centred on zero, scaled so +-40 points fills a side; the signed number is always printed. */
function DeltaBar({ delta }: { delta: number | null | undefined }) {
  if (delta == null) return <span className="text-subtle">-</span>;
  const w = Math.min(32, (Math.abs(delta) / 40) * 32);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative inline-block h-2 w-16 rounded-xs bg-sunken" aria-hidden>
        <span className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
        {delta !== 0 && <span className="absolute inset-y-0 rounded-xs" style={{ width: w, [delta < 0 ? "right" : "left"]: "50%", background: delta < 0 ? "var(--score-2)" : "var(--score-5)" }} />}
      </span>
      <span className="mono text-sm">{signed(delta, 1)}</span>
    </span>
  );
}

function DiffHeatmap({ cells, headCall }: { cells: Compared[]; headCall: Map<string, string> }) {
  const multi = new Set(cells.map((c) => c.profile)).size > 1;
  const { rows, cols, map } = useMemo(() => {
    const colName = (c: Compared) => (multi ? `${c.persona} / ${c.profile}` : c.persona);
    const map = new Map(cells.map((c) => [`${c.scenario}\u0000${colName(c)}`, c]));
    return { rows: [...new Set(cells.map((c) => c.scenario))].sort(), cols: [...new Set(cells.map(colName))].sort(), map };
  }, [cells, multi]);
  const grid = useRef<HTMLDivElement>(null);
  const onKey = (e: React.KeyboardEvent, r: number, c: number) => {
    const d: Record<string, [number, number]> = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
    const mv = d[e.key];
    if (!mv) return;
    e.preventDefault();
    grid.current?.querySelector<HTMLElement>(`[data-cell="${r + mv[0]}-${c + mv[1]}"]`)?.focus();
  };
  return (
    <>
      <div className="overflow-x-auto">
        <div ref={grid} role="grid" aria-label="Diff matrix, scenarios by personas" className="grid w-full gap-0.5" style={{ gridTemplateColumns: `minmax(140px,220px) repeat(${cols.length}, minmax(72px,1fr))`, maxWidth: 220 + cols.length * 160 }}>
          <div role="row" className="contents">
            <div role="columnheader" className="bg-surface" />
            {cols.map((c) => <div key={c} role="columnheader" className="truncate px-1 pb-1 text-center text-xs text-muted" title={c}>{c}</div>)}
          </div>
          {rows.map((r, ri) => (
            <div role="row" key={r} className="contents">
              <div role="rowheader" className="flex items-center bg-surface pr-2 text-sm text-muted" title={r}><span className="line-clamp-2">{r}</span></div>
              {cols.map((col, ci) => {
                const c = map.get(`${r}\u0000${col}`);
                return <DiffCell key={col} c={c} r={r} col={col} ri={ri} ci={ci} onKey={onKey} callId={c ? headCall.get(cellKey(c.scenario, c.persona, c.profile)) : undefined} />;
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>Cell shows the head score; the small number is the change from base.</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3.5 w-5 rounded-xs border-2 border-fg" aria-hidden />newly failing</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3.5 w-5 rounded-xs opacity-45" style={stepStyle(4)} aria-hidden />unchanged</span>
      </p>
    </>
  );
}

function DiffCell({ c, r, col, ri, ci, onKey, callId }: { c?: Compared; r: string; col: string; ri: number; ci: number; onKey: (e: React.KeyboardEvent, r: number, c: number) => void; callId?: string }) {
  const nav = { "data-cell": `${ri}-${ci}`, role: "gridcell" as const, onKeyDown: (e: React.KeyboardEvent) => onKey(e, ri, ci), tabIndex: ri === 0 && ci === 0 ? 0 : -1 };
  const cls = "relative flex h-10 min-w-14 items-center justify-center overflow-hidden rounded-xs mono text-sm font-medium outline-offset-2";
  if (!c) return <div {...nav} className={cls} style={stepStyle(null)} aria-label={`${r}, ${col}: not in either run`}><Minus size={14} aria-hidden /></div>;
  const g = groupOf(c);
  const muted = g === "unchanged";
  const label = `${r}, ${col}: head ${c.head_score != null ? fmtScore(c.head_score) : "not scored"}${c.delta != null ? `, ${c.delta === 0 ? "unchanged" : `${signed(c.delta, 1)} from base`}` : ""}${c.newly_failing ? ", newly failing" : ""}`;
  const inner = (
    <>
      {muted && <span className="absolute inset-0 opacity-45" style={stepStyle(c.head_score != null ? overallStep(c.head_score) : null)} aria-hidden />}
      <span className="relative" style={muted ? { color: "var(--fg)" } : undefined}>{c.head_score != null ? fmtScore(c.head_score) : "-"}</span>
      {c.delta != null && c.delta !== 0 && <span className="absolute bottom-0 left-0.5 text-[10px] font-normal" aria-hidden>{signed(c.delta)}</span>}
    </>
  );
  const style = muted ? undefined : stepStyle(c.head_score != null ? overallStep(c.head_score) : null);
  const className = cn(cls, c.newly_failing && "outline outline-2 outline-[var(--fg)] -outline-offset-2");
  return callId ? <Link {...nav} href={`/calls/${callId}`} aria-label={label} title={label} className={className} style={style}>{inner}</Link> : <div {...nav} aria-label={label} title={label} className={className} style={style}>{inner}</div>;
}

function DimensionDeltas({ base, head, loading, failed }: { base: Record<string, number | undefined>; head: Record<string, number | undefined>; loading: boolean; failed: boolean }) {
  if (loading) return <div role="status" aria-label="Loading dimensions" aria-busy="true" className="flex flex-col gap-2">{RUBRIC.map((d) => <Skeleton key={d.key} className="h-5" />)}</div>;
  if (failed) return <p className="text-sm text-muted">Some call evaluations could not be loaded, so dimension means are incomplete.</p>;
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Mean dimension score per run</caption>
      <thead><tr className="text-left text-xs text-muted"><th scope="col" className="pb-1 font-normal">Dimension</th><th scope="col" className="pb-1 text-right font-normal">Base</th><th scope="col" className="pb-1 text-right font-normal">Head</th><th scope="col" className="pb-1 text-right font-normal">Delta</th></tr></thead>
      <tbody>
        {RUBRIC.map((d) => {
          const bv = base[d.key];
          const hv = head[d.key];
          const delta = bv != null && hv != null ? hv - bv : null;
          const Icon = delta == null || Math.abs(delta) < 0.005 ? Minus : delta > 0 ? ArrowUp : ArrowDown;
          const tone = delta == null || Math.abs(delta) < 0.005 ? "text-muted" : delta > 0 ? "text-pass-fg" : "text-fail-fg";
          return (
            <tr key={d.key} className="border-t border-border">
              <th scope="row" className="py-1.5 pr-2 text-left font-normal">{d.label}</th>
              <td className="mono py-1.5 text-right">{bv != null ? bv.toFixed(2) : "-"}</td>
              <td className="mono py-1.5 text-right">{hv != null ? hv.toFixed(2) : "-"}</td>
              <td className={cn("mono py-1.5 text-right", tone)}><span className="inline-flex items-center justify-end gap-1"><Icon size={12} strokeWidth={1.6} aria-hidden />{delta == null ? "-" : signed(delta, 2)}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

type AgentData = { name: string; description: string; mandatory_disclosures?: { text: string }[]; forbidden_phrases?: { text: string }[]; expected_tools?: { name: string }[] };

function AgentDiff({ same, base, head, loading }: { same: boolean; base?: AgentData; head?: AgentData; loading: boolean }) {
  if (same) return <p className="text-sm text-muted">Both runs used the same agent. The API does not expose per-run config snapshots, so edits made between the two runs cannot be listed here.</p>;
  if (loading || !base || !head) return <Skeleton className="h-24" />;
  const groups: [string, { text: string; kind: "added" | "removed" }[]][] = [
    ["Description", base.description === head.description ? [] : [{ text: base.description, kind: "removed" }, { text: head.description, kind: "added" }]],
    ["Disclosures", listDiff((base.mandatory_disclosures ?? []).map((x) => x.text), (head.mandatory_disclosures ?? []).map((x) => x.text))],
    ["Forbidden phrases", listDiff((base.forbidden_phrases ?? []).map((x) => x.text), (head.forbidden_phrases ?? []).map((x) => x.text))],
    ["Tools", listDiff((base.expected_tools ?? []).map((x) => x.name), (head.expected_tools ?? []).map((x) => x.name))],
  ];
  const any = groups.some(([, l]) => l.length);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="text-xs text-subtle">Current config of {base.name} (base) and {head.name} (head).</p>
      {!any && <p className="text-muted">The two agents have the same description, disclosures, forbidden phrases and tools.</p>}
      {groups.filter(([, l]) => l.length).map(([name, lines]) => (
        <div key={name}>
          <h3 className="eyebrow mb-1">{name}</h3>
          <ul className="flex flex-col gap-1">
            {lines.map((l, i) => (
              <li key={i} className="flex items-start gap-2">
                {l.kind === "added" ? <Plus size={14} strokeWidth={1.6} className="mt-0.5 shrink-0 text-pass-fg" aria-label="added" role="img" /> : <Minus size={14} strokeWidth={1.6} className="mt-0.5 shrink-0 text-fail-fg" aria-label="removed" role="img" />}
                <span className={l.kind === "removed" ? "text-muted line-through" : undefined}>{l.text}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
