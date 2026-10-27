"use client";

import Link from "next/link";
import { useMemo, useRef } from "react";
import { CircleX, Clock, Minus } from "lucide-react";
import type { RunItem } from "@/lib/api/runs";
import { fmtScore, overallStep, stepStyle } from "@/components/ui/measure";
import { cn } from "@/lib/utils";

const NOT_DONE = new Set(["queued", "connecting", "in_progress", "completed", "evaluating"]);

type Cell = { items: RunItem[]; shown: RunItem | null };

/** Worst evaluated item of a cell (lowest score; critical first), else any in-flight item. */
function pick(items: RunItem[]): RunItem | null {
  const scored = items.filter((i) => i.overall_score !== null && i.overall_score !== undefined);
  if (scored.length) return scored.reduce((a, b) => (b.overall_score! < a.overall_score! ? b : a));
  return items[0] ?? null;
}

export function Heatmap({ items, line, sortBy, flashIds, runKey }: { items: RunItem[]; line: string; sortBy: "worst" | "name"; flashIds: Set<string>; runKey: string }) {
  const { rows, cols, cells } = useMemo(() => {
    const sel = line === "all" ? items : items.filter((i) => i.noise_profile === line);
    const map = new Map<string, RunItem[]>();
    for (const i of items.filter((x) => line === "all" || x.noise_profile === line)) {
      const k = `${i.scenario}\u0000${i.persona}`;
      map.set(k, [...(map.get(k) ?? []), i]);
    }
    const worst = (names: string[], by: (i: RunItem) => string) =>
      [...names].sort((a, b) => {
        if (sortBy === "name") return a.localeCompare(b);
        const m = (n: string) => Math.min(...sel.filter((i) => by(i) === n && i.overall_score != null).map((i) => i.overall_score as number), 101);
        return m(a) - m(b) || a.localeCompare(b);
      });
    const rows = worst([...new Set(items.map((i) => i.scenario))], (i) => i.scenario);
    const cols = worst([...new Set(items.map((i) => i.persona))], (i) => i.persona);
    const cells = new Map<string, Cell>();
    for (const [k, v] of map) cells.set(k, { items: v, shown: pick(v) });
    return { rows, cols, cells };
  }, [items, line, sortBy]);

  const grid = useRef<HTMLDivElement>(null);
  function onKey(e: React.KeyboardEvent, r: number, c: number) {
    const d: Record<string, [number, number]> = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
    const mv = d[e.key];
    if (!mv) return;
    e.preventDefault();
    const next = grid.current?.querySelector<HTMLElement>(`[data-cell="${r + mv[0]}-${c + mv[1]}"]`);
    next?.focus();
  }

  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <div ref={grid} role="grid" aria-label={`Run matrix, scenarios by personas`} className="grid w-full gap-0.5" style={{ gridTemplateColumns: `minmax(140px,220px) repeat(${cols.length}, minmax(64px,1fr))` }}>
        <div role="row" className="contents">
          <div role="columnheader" className="sticky left-0 bg-surface" />
          {cols.map((c) => (
            <div key={c} role="columnheader" className="truncate px-1 pb-1 text-center text-xs text-muted" title={c}>
              {c}
            </div>
          ))}
        </div>
        {rows.map((r, ri) => (
          <div role="row" key={r} className="contents">
            <div role="rowheader" className="sticky left-0 flex items-center bg-surface pr-2 text-sm text-muted" title={r}>
              <span className="line-clamp-2">{r}</span>
            </div>
            {cols.map((c, ci) => {
              const cell = cells.get(`${r}\u0000${c}`);
              return <HeatCell key={c} cell={cell} r={r} c={c} ri={ri} ci={ci} onKey={onKey} flash={!!cell?.shown && flashIds.has(cell.shown.id)} runKey={runKey} />;
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function HeatCell({ cell, r, c, ri, ci, onKey, flash, runKey }: { cell?: Cell; r: string; c: string; ri: number; ci: number; onKey: (e: React.KeyboardEvent, r: number, c: number) => void; flash: boolean; runKey: string }) {
  const base = cn("relative flex h-10 min-w-14 items-center justify-center rounded-xs mono text-sm font-medium outline-offset-2", flash && "flash-in");
  const dn = { "data-cell": `${ri}-${ci}`, role: "gridcell" as const, onKeyDown: (e: React.KeyboardEvent) => onKey(e, ri, ci), tabIndex: ri === 0 && ci === 0 ? 0 : -1 };
  const it = cell?.shown;
  if (!it) return <div {...dn} className={base} style={stepStyle(null)} aria-label={`Scenario ${r}, persona ${c}, no call planned`}><Minus size={14} aria-hidden /></div>;
  const score = it.overall_score;
  const many = cell.items.length > 1;
  const verdict = it.critical_failure ? "critical" : it.passed === false ? "fail" : it.passed ? "pass" : "not scored";
  const label = `Scenario ${r}, persona ${c}, line ${it.noise_profile}${score != null ? `, score ${fmtScore(score)}, ${verdict}` : `, ${it.status.replace("_", " ")}`}${many ? `, worst of ${cell.items.length}` : ""}`;
  const tip = `${r} / ${c} / ${it.noise_profile}: ${score != null ? `${fmtScore(score)} ${verdict}` : it.status.replace("_", " ")}`;
  const inner =
    score != null ? (
      <>
        {fmtScore(score)}
        {it.critical_failure && <span className="absolute right-0 top-0 h-0 w-0 border-l-[10px] border-t-[10px] border-l-transparent border-t-[var(--fg)]" aria-hidden />}
        {many && <span className="absolute bottom-0 right-0.5 text-[11px] font-normal">x{cell.items.length}</span>}
      </>
    ) : it.status === "error" || it.status === "judge_error" ? (
      <CircleX size={16} strokeWidth={1.6} aria-hidden />
    ) : it.status === "cancelled" || it.status === "skipped_budget" ? (
      <Minus size={14} aria-hidden />
    ) : NOT_DONE.has(it.status) && it.status !== "queued" ? (
      <span className="spinner" aria-hidden />
    ) : (
      <Clock size={14} strokeWidth={1.6} aria-hidden />
    );
  const style = stepStyle(score != null ? overallStep(score) : null);
  if (it.call_id)
    return (
      <Link {...dn} href={`/calls/${it.call_id}?from=${runKey}`} title={tip} aria-label={label} className={base} style={style}>
        {inner}
      </Link>
    );
  return (
    <div {...dn} title={tip} aria-label={label} className={base} style={style}>
      {inner}
    </div>
  );
}

export function HeatmapLegend() {
  const items: [number, string][] = [
    [1, "below 40"],
    [2, "40-59"],
    [3, "60-79"],
    [4, "80-89"],
    [5, "90+"],
  ];
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted" aria-label="Score legend">
      {items.map(([n, label]) => (
        <span key={n} className="inline-flex items-center gap-1.5">
          <span className="h-3 w-5 rounded-xs" style={stepStyle(n as 1 | 2 | 3 | 4 | 5)} aria-hidden />
          <span className="mono">{label}</span>
          {n === 3 && <span className="ml-1 inline-block h-3.5 w-0.5 bg-fg" title="Pass line at 80" aria-hidden />}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-5 rounded-xs" style={stepStyle(null)} aria-hidden />
        not run
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-0 w-0 border-l-[10px] border-t-[10px] border-l-transparent border-t-[var(--fg)]" aria-hidden />
        critical
      </span>
      <span>Pass line 80</span>
    </div>
  );
}
