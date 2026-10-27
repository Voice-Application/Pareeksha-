"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Languages } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { EmptyState, ErrorPanel, NotEnabled, isNotImplemented, TableSkeleton, PageError } from "@/components/ui/states";
import { Segmented } from "@/components/ui/field";
import { ProgressBar, stepStyle } from "@/components/ui/measure";
import { CONDITION_ORDER, LOW_N, METRIC_LABEL, METRIC_NOTE, metricLegend, metricStep, type Metric } from "@/lib/dialect-scale";
import { CodeBlock } from "@/components/ops/code-block";
import { cn } from "@/lib/utils";

/** Low-sample hatch as an SVG pattern (shape, not colour; no gradient). */
const HATCH = `url("data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="6" height="6"><path d="M-1 1l2-2M0 6l6-6M5 7l2-2" stroke="black" stroke-opacity="0.25" stroke-width="1"/></svg>')}")`;

const SYNTHETIC = /synthetic/i;

export function DialectIndex() {
  const datasets = useQuery({ queryKey: ["dialect-datasets"], queryFn: () => call(api.GET("/api/v1/dialect-datasets")), retry: false });
  const reports = useQuery({ queryKey: ["dialect-reports"], queryFn: () => call(api.GET("/api/v1/dialect-reports")), retry: false });
  const ds = datasets.data?.items ?? [];
  const rs = reports.data?.items ?? [];
  const off = isNotImplemented(datasets.error) || isNotImplemented(reports.error);
  return (
    <>
      <PageHeader eyebrow={datasets.isSuccess ? `${ds.length} dataset${ds.length === 1 ? "" : "s"}, ${rs.length} report${rs.length === 1 ? "" : "s"}` : ""} title="Dialect gap report" description="Measure how the speech recogniser performs per dialect and phone line, with sample sizes and confidence intervals." actions={<Button variant="primary" disabled={off} title={off ? "Dialect evaluation is not enabled in this build" : undefined}>New dataset</Button>} />
      {off ? (
        <Panel><NotEnabled icon={Languages} what="Dialect evaluation" error={datasets.error ?? reports.error} /></Panel>
      ) : (
        <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
          <Panel title="Datasets" bodyClassName="p-0">
            {datasets.isPending ? <TableSkeleton rows={3} /> : datasets.isError ? <div className="p-4"><ErrorPanel error={datasets.error} what="datasets" onRetry={() => void datasets.refetch()} /></div> : ds.length === 0 ? (
              <EmptyState icon={Languages} title="No datasets yet" body="A dataset is a set of consented, labelled clips of one language, grouped by dialect." />
            ) : (
              <ul className="divide-y divide-border">
                {ds.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div><p className="font-medium">{d.name}</p><p className="text-xs text-muted">{d.description}</p></div>
                    <Chip mono>{d.sample_count} clips</Chip>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel title="Reports" bodyClassName="p-0">
            {reports.isPending ? <TableSkeleton rows={3} /> : reports.isError ? <div className="p-4"><ErrorPanel error={reports.error} what="reports" onRetry={() => void reports.refetch()} /></div> : rs.length === 0 ? (
              <p className="p-4 text-sm text-subtle">No reports yet. Evaluate a dataset to create one.</p>
            ) : (
              <ul className="divide-y divide-border">
                {rs.map((r) => (
                  <li key={r.id} className="flex flex-col gap-1 px-4 py-3">
                    <Link className="font-medium underline-offset-2 hover:underline" href={`/dialect/${r.id}`}>Report {r.id.slice(0, 8)}</Link>
                    <p className="text-xs text-muted">{r.engines.join(", ")} · {r.conditions.length} conditions · <time dateTime={r.created_at}>{relativeTime(r.created_at)}</time></p>
                    <ProgressBar done={r.progress.done} total={r.progress.expected_results} label="Report progress" />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}

export function DialectReport({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["dialect-report", id], queryFn: () => call(api.GET("/api/v1/dialect-reports/{report_id}", { params: { path: { report_id: id } } })), retry: false });
  const [metric, setMetric] = useState<Metric>("wer");
  const [pick, setPick] = useState<{ dialect: string; condition: string } | null>(null);
  const clips = useQueryClips(id, pick);
  // aggregates[dialect][condition][engine]
  const { engine, rows, conditions, cells } = useMemo(() => {
    const agg = q.data?.aggregates ?? {};
    const engine = Object.values(Object.values(agg)[0] ?? {})[0] ? Object.keys(Object.values(Object.values(agg)[0] ?? {})[0]!)[0] : "";
    const conds = [...new Set(Object.values(agg).flatMap((c) => Object.keys(c)))].sort((a, b) => (CONDITION_ORDER.indexOf(a) + 99) % 99 - (CONDITION_ORDER.indexOf(b) + 99) % 99);
    const val = (a: { wer: number; cer: number; entity_acc?: number | null }) => (metric === "entity_acc" ? a.entity_acc ?? null : a[metric]);
    const worst = (d: string) => Math.max(...conds.map((c) => { const a = agg[d]?.[c]?.[engine]; const v = a ? val(a) : null; return v === null || v === undefined ? -1 : metric === "entity_acc" ? 1 - v : v; }));
    const rows = Object.keys(agg).sort((a, b) => worst(b) - worst(a));
    return { engine, rows, conditions: conds, cells: agg };
  }, [q.data, metric]);

  if (q.isError) return isNotImplemented(q.error) ? (<><PageHeader title="Dialect report" /><Panel><NotEnabled icon={Languages} what="Dialect reports" error={q.error} /></Panel></>) : <PageError error={q.error} onRetry={() => void q.refetch()} backHref="/dialect" backLabel="Back to dialect" />;
  if (q.isPending) return <TableSkeleton rows={5} />;
  const r = q.data;
  let worstCell: { d: string; c: string; v: number; n: number } | null = null;
  for (const d of rows) for (const c of conditions) {
    const a = cells[d]?.[c]?.[engine];
    const v = a ? (metric === "entity_acc" ? a.entity_acc ?? null : a[metric]) : null;
    if (a && v !== null && (!worstCell || (metric === "entity_acc" ? v < worstCell.v : v > worstCell.v))) worstCell = { d, c, v, n: a.n };
  }
  const title = !worstCell || worstCell.n < LOW_N ? "Not enough clips to rank dialects yet" : `${worstCell.d} on ${worstCell.c} has the worst ${METRIC_LABEL[metric]}: ${Math.round(worstCell.v * 100)}%`;
  const sel = pick ? cells[pick.dialect]?.[pick.condition]?.[engine] : undefined;
  return (
    <>
      <PageHeader
        eyebrow={`${engine || "engine"} | ${r.progress.done} of ${r.progress.expected_results} results`}
        title={title}
        description={worstCell ? `Based on ${worstCell.n} clips in the worst cell.` : undefined}
        actions={<>
          <Segmented hideLabel label="Metric" value={metric} onChange={setMetric} options={(Object.keys(METRIC_LABEL) as Metric[]).map((m) => ({ value: m, label: METRIC_LABEL[m] }))} />
          <LinkButton href={`/api/proxy/api/v1/dialect-reports/${id}/html`} target="_blank">Export HTML</LinkButton>
        </>}
      />
      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Panel title="Dialect by condition" aux={<span className="text-xs">{METRIC_NOTE[metric]}</span>}>
            {rows.length === 0 ? <p className="text-sm text-subtle">No results yet.</p> : (
              <div className="overflow-x-auto">
                <div role="grid" aria-label={`${METRIC_LABEL[metric]} by dialect and condition`} className="grid gap-0.5" style={{ gridTemplateColumns: `minmax(120px,200px) repeat(${conditions.length}, minmax(88px,1fr))` }}>
                  <div role="row" className="contents"><div role="columnheader" /> {conditions.map((c) => <div key={c} role="columnheader" className="mono px-1 pb-1 text-center text-xs text-muted">{c}</div>)}</div>
                  {rows.map((d) => (
                    <div role="row" key={d} className="contents">
                      <div role="rowheader" className="flex flex-wrap items-center gap-1.5 text-sm text-muted">{d.replace(/\s*\(?synthetic\)?\s*$/i, "")}{SYNTHETIC.test(d) && <Chip>synthetic</Chip>}</div>
                      {conditions.map((c) => {
                        const a = cells[d]?.[c]?.[engine];
                        const v = a ? (metric === "entity_acc" ? a.entity_acc ?? null : a[metric]) : null;
                        if (!a || v === null) return <div key={c} role="gridcell" className="flex h-12 items-center justify-center rounded-xs" style={stepStyle(null)}>-</div>;
                        const low = a.n < LOW_N;
                        return (
                          <button key={c} type="button" role="gridcell" aria-label={`Dialect ${d}, ${c}, ${METRIC_LABEL[metric]} ${Math.round(v * 100)}%, ${a.n} clips, 95% interval ${Math.round(a.wer_ci[0] * 100)} to ${Math.round(a.wer_ci[1] * 100)}${low ? ", low sample" : ""}`} onClick={() => setPick({ dialect: d, condition: c })} className={cn("mono flex h-12 flex-col items-center justify-center rounded-xs text-sm font-medium", pick?.dialect === d && pick.condition === c && "outline outline-2 outline-offset-1 outline-[var(--accent)]")} style={{ ...stepStyle(metricStep(metric, v)), backgroundImage: low ? HATCH : undefined }}>
                            {Math.round(v * 100)}%
                            <span className="text-[11px] font-normal">n={a.n}{low ? " low n" : ""}</span>
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted" aria-label="Legend">
                  {metricLegend(metric).map(([s, l]) => <span key={s} className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded-xs" style={stepStyle(s)} aria-hidden /><span className="mono">{l}</span></span>)}
                  <span>Hatched: fewer than {LOW_N} clips</span>
                  {rows.some((d) => SYNTHETIC.test(d)) && <span>Synthetic: clips generated by text-to-speech, not real speakers.</span>}
                </div>
              </div>
            )}
          </Panel>
          <Panel title="Top misrecognised words" bodyClassName="p-0">
            {r.top_errors?.length ? (
              <table className="rt"><caption className="sr-only">Top misrecognised words</caption><thead><tr><th scope="col">Reference</th><th scope="col">Heard</th><th scope="col">Count</th></tr></thead><tbody>
                {r.top_errors.map((e, i) => <tr key={i}><td lang="kn">{e.ref}</td><td lang="kn">{e.hyp}</td><td className="mono">{e.count}</td></tr>)}
              </tbody></table>
            ) : <p className="p-4 text-sm text-subtle">No recurring errors yet.</p>}
          </Panel>
        </div>
        <div className="flex flex-col gap-6">
          <Panel title="Selected cell">
            {!pick || !sel ? <p className="text-sm text-subtle">Select a cell to see its value, interval and worst clips.</p> : (
              <div className="flex flex-col gap-3 text-sm">
                <p className="font-medium">{pick.dialect} on {pick.condition}</p>
                <dl className="grid grid-cols-2 gap-2">
                  <div><dt className="eyebrow">WER</dt><dd className="mono">{(sel.wer * 100).toFixed(1)}%</dd></div>
                  <div><dt className="eyebrow">95% CI</dt><dd className="mono">{(sel.wer_ci[0] * 100).toFixed(0)}-{(sel.wer_ci[1] * 100).toFixed(0)}%</dd></div>
                  <div><dt className="eyebrow">CER</dt><dd className="mono">{(sel.cer * 100).toFixed(1)}%</dd></div>
                  <div><dt className="eyebrow">Entity accuracy</dt><dd className="mono">{sel.entity_acc == null ? "-" : `${(sel.entity_acc * 100).toFixed(0)}%`}</dd></div>
                </dl>
                <p className="eyebrow">Worst clips</p>
                {clips.isPending ? <p className="text-subtle">Loading clips…</p> : (clips.data ?? []).slice(0, 10).map((c) => (
                  <div key={c.sample_id + c.engine} className="rounded-sm border border-border p-2">
                    <p lang="kn" className="text-sm">{c.reference_text}</p><p lang="kn" className="text-sm text-muted">{c.hypothesis_text}</p>
                    <p className="mono text-xs text-subtle">WER {(c.wer * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
            )}
          </Panel>
          <Panel title="Bias list suggestions">
            {r.bias_suggestions?.length ? <><div className="mb-2 flex flex-wrap gap-1">{r.bias_suggestions.map((b) => <Chip key={b} mono>{b}</Chip>)}</div><CodeBlock label="bias list" text={r.bias_suggestions.join("\n")} /></> : <p className="text-sm text-subtle">No suggestions yet.</p>}
          </Panel>
        </div>
      </div>
    </>
  );
}

function useQueryClips(id: string, pick: { dialect: string; condition: string } | null) {
  return useQuery({
    queryKey: ["dialect-clips", id, pick],
    enabled: !!pick,
    retry: false,
    queryFn: async () => (await call(api.GET("/api/v1/dialect-reports/{report_id}/clips", { params: { path: { report_id: id }, query: { dialect: pick!.dialect, condition: pick!.condition } } }))).items,
  });
}
