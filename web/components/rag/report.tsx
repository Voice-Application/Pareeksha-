"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { getReport, inr, ms, pct, pctCi, type ReportRow } from "@/lib/api/rag";
import { Chip, PageHeader, Panel } from "@/components/ui/layout";
import { PageError, Skeleton } from "@/components/ui/states";
import { NumberField } from "@/components/ui/field";

const DONE = new Set(["completed", "failed", "cancelled"]);
const KIND_LABEL: Record<ReportRow["kind"], string> = { rag: "RAG", no_rag: "no-RAG baseline", full_context: "full-context baseline" };

const NA = ({ why }: { why: string }) => (
  <span className="text-subtle" title={why}>
    n/a
  </span>
);

const num = (x: number) => x.toLocaleString("en-IN");

function noRetrieval(kind: ReportRow["kind"]) {
  return kind === "rag" ? "No ground-truth questions were scored for this run yet." : `${KIND_LABEL[kind]}: nothing is retrieved, so retrieval is not scored.`;
}

type Bar = { label: string; values: { name: string; value: number | null | undefined; tone: string }[] };

/** Horizontal grouped bars in plain SVG. A missing value prints its reason instead of a bar. */
function BarChart({ title, bars, fmt, missing }: { title: string; bars: Bar[]; fmt: (v: number) => string; missing: string }) {
  const W = 560;
  const L = 150;
  const rowH = 22;
  const groupH = bars[0] ? bars[0].values.length * rowH + 14 : 0;
  const max = Math.max(1, ...bars.flatMap((b) => b.values.map((v) => v.value ?? 0)));
  const H = bars.length * groupH;
  const desc = bars.map((b) => `${b.label}: ${b.values.map((v) => `${v.name} ${v.value == null ? missing : fmt(v.value)}`).join(", ")}`).join("; ");
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 text-sm font-medium">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${title}. ${desc}`}>
        {bars.map((b, gi) => (
          <g key={b.label} transform={`translate(0 ${gi * groupH})`}>
            <text x={L - 8} y={14} textAnchor="end" fontSize="12" fill="var(--fg)">
              {b.label.length > 22 ? `${b.label.slice(0, 21)}…` : b.label}
            </text>
            {b.values.map((v, vi) => {
              const y = vi * rowH;
              const w = v.value == null ? 0 : Math.max(2, (v.value / max) * (W - L - 90));
              return (
                <g key={v.name}>
                  <text x={L} y={y + 14} fontSize="0" aria-hidden>
                    {v.name}
                  </text>
                  {v.value != null && <rect x={L} y={y + 3} width={w} height={rowH - 8} rx="2" fill={v.tone} />}
                  <text x={L + w + 6} y={y + 15} className="num" fontSize="11" fill="var(--fg-muted)">
                    {v.name} {v.value == null ? missing : fmt(v.value)}
                  </text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    </figure>
  );
}

export function RagReportView({ id }: { id: string }) {
  const [monthly, setMonthly] = useState("10000");
  const m = Math.max(1, Math.floor(Number(monthly)) || 10000);
  const q = useQuery({
    queryKey: ["rag-report", id, m],
    queryFn: () => getReport(id, m),
    retry: false,
    refetchInterval: (s) => ((s.state.data?.rows ?? []).some((r) => r.run_id && r.run_status && !DONE.has(r.run_status)) ? 5000 : false),
  });

  if (q.isError) return <PageError error={q.error} onRetry={() => void q.refetch()} backHref="/rag-lab" backLabel="Back to the RAG lab" />;
  const rows = q.data?.rows ?? [];
  const noRag = rows.find((r) => r.kind === "no_rag" && r.run_id);
  const rec = q.data?.recommendation;

  return (
    <>
      <PageHeader
        title="RAG report"
        eyebrow={
          <>
            <Link href="/rag-lab" className="text-accent-fg underline-offset-2 hover:underline">
              RAG lab
            </Link>
            <Link href="/settings/pricing" className="text-accent-fg underline-offset-2 hover:underline">
              Prices
            </Link>
          </>
        }
        description="One row per setup. n is shown on every row; ranges are 95% Wilson intervals."
        actions={<NumberField id="monthly" label="Conversations per month" min={1} value={monthly} onChange={(e) => setMonthly(e.target.value)} fieldClassName="w-48" />}
      />

      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.data && rec && (
        <section aria-label="Recommendation" className={`mb-6 flex items-start gap-3 rounded-md px-5 py-4 ${rec.label ? "bg-pass-tint" : "bg-warn-tint"}`}>
          {rec.label ? <CircleCheck size={18} strokeWidth={1.6} className="mt-0.5 shrink-0 text-pass-fg" aria-hidden /> : <TriangleAlert size={18} strokeWidth={1.6} className="mt-0.5 shrink-0 text-warn-fg" aria-hidden />}
          <div className="min-w-0">
            <h2 className="display text-md">{rec.label ? `Recommendation: ${rec.label}` : "No recommendation yet"}</h2>
            <p className="mt-1 max-w-[72ch] text-sm">{rec.reason}</p>
          </div>
        </section>
      )}

      {q.data && (
        <div className="grid gap-6">
          <Panel title="Results" bodyClassName="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1180px] border-collapse text-sm">
                <caption className="sr-only">RAG report, one row per setup</caption>
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted">
                    {["Setup", "n calls / questions", "Hit rate (95% CI)", "MRR", "Context precision", "Faithfulness", "Hallucination (95% CI)", "Answer correct", "Refusal correct", "Retrieval p50 / p95", "Turn p50 / p95", "Tokens per conversation", "₹ per conversation", "Monthly ₹", "Saving vs full context", "Saving vs no-RAG"].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    if (!r.run_id)
                      return (
                        <tr key={r.label} className="border-b border-border last:border-0">
                          <th scope="row" className="px-3 py-3 text-left font-medium align-top">
                            {r.label}
                            <div className="mt-1">
                              <Chip>{KIND_LABEL[r.kind]}</Chip>
                            </div>
                          </th>
                          <td colSpan={15} className="px-3 py-3 text-muted">
                            <strong className="font-medium text-warn-fg">n/a</strong> {r.status_note ?? "This setup has no run."} It is shown, not truncated or guessed.
                          </td>
                        </tr>
                      );
                    const ret: { hit_rate?: number | null; hit_rate_ci?: number[] | null; mrr?: number | null; context_precision?: number | null } = r.retrieval ?? {};
                    const gen: { faithfulness?: number | null; n_judged?: number; hallucination_rate?: number | null; hallucination_ci?: number[] | null; answer_correct_rate?: number | null; refusal_correct_rate?: number | null; skipped?: Record<string, number> } = r.generation ?? {};
                    const lat: NonNullable<ReportRow["latency_ms"]> = r.latency_ms ?? {};
                    const tok = r.tokens_per_conversation;
                    const skipped = Object.entries(gen.skipped ?? {});
                    const why = noRetrieval(r.kind);
                    return (
                      <tr key={r.label} className="border-b border-border align-top last:border-0">
                        <th scope="row" className="px-3 py-3 text-left font-medium">
                          {r.label}
                          <div className="mt-1 flex flex-wrap items-center gap-1">
                            <Chip>{KIND_LABEL[r.kind]}</Chip>
                            {r.run_status && <Chip>{r.run_status}</Chip>}
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-3 text-xs font-normal">
                            <Link href={`/runs/${r.run_id}`} className="text-accent-fg underline-offset-2 hover:underline">
                              Run
                            </Link>
                            {noRag && r.run_id !== noRag.run_id && (
                              <Link href={`/runs/compare?base=${noRag.run_id}&head=${r.run_id}`} className="text-accent-fg underline-offset-2 hover:underline">
                                Compare to no-RAG
                              </Link>
                            )}
                          </div>
                        </th>
                        <td className="num px-3 py-3">
                          {num(r.n_calls)} / {num(r.n_questions_with_truth)}
                        </td>
                        <td className="num px-3 py-3">{ret.hit_rate == null ? <NA why={why} /> : pctCi(ret.hit_rate, ret.hit_rate_ci)}</td>
                        <td className="num px-3 py-3">{ret.mrr == null ? <NA why={why} /> : ret.mrr.toFixed(2)}</td>
                        <td className="num px-3 py-3">{ret.context_precision == null ? <NA why={why} /> : pct(ret.context_precision)}</td>
                        <td className="num px-3 py-3">
                          {gen.faithfulness == null ? <NA why="Not judged: the judge was skipped or no answers were scored." /> : <>{pct(gen.faithfulness)} <span className="text-xs text-muted">n={num(gen.n_judged ?? 0)}</span></>}
                          {skipped.length > 0 && <div className="text-xs text-muted">skipped: {skipped.map(([k, v]) => `${k} ×${v}`).join(", ")}</div>}
                        </td>
                        <td className="num px-3 py-3">{gen.hallucination_rate == null ? <NA why="Not judged." /> : pctCi(gen.hallucination_rate, gen.hallucination_ci)}</td>
                        <td className="num px-3 py-3">{gen.answer_correct_rate == null ? <NA why="Not judged." /> : pct(gen.answer_correct_rate)}</td>
                        <td className="num px-3 py-3">{gen.refusal_correct_rate == null ? <NA why="No unanswerable questions were judged." /> : pct(gen.refusal_correct_rate)}</td>
                        <td className="num px-3 py-3">{lat.retrieval_p50 == null ? <NA why={why} /> : `${ms(lat.retrieval_p50)} / ${ms(lat.retrieval_p95)}`}</td>
                        <td className="num px-3 py-3">
                          {ms(lat.turn_p50)} / {ms(lat.turn_p95)}
                        </td>
                        <td className="num px-3 py-3">
                          {tok ? (
                            <>
                              {num(tok.agent_input)} in, {num(tok.agent_output)} out
                              {(tok.query_embedding > 0 || tok.rerank > 0) && <div className="text-xs text-muted">+ {num(tok.query_embedding)} embed, {num(tok.rerank)} rerank</div>}
                            </>
                          ) : (
                            <NA why="No token usage recorded." />
                          )}
                        </td>
                        <td className="num px-3 py-3">{r.cost_per_conversation_inr == null ? <span className="text-subtle" title="A model used by this run has no price. Add one on the Pricing page.">unpriced</span> : inr(r.cost_per_conversation_inr, 4)}</td>
                        <td className="num px-3 py-3">{r.monthly_cost_inr == null ? <span className="text-subtle">unpriced</span> : inr(r.monthly_cost_inr, 0)}</td>
                        <td className="num px-3 py-3">
                          {r.savings_vs_full_context ? `${inr(r.savings_vs_full_context.inr, 0)} (${r.savings_vs_full_context.pct.toFixed(0)}%)` : r.token_savings_vs_full_context_pct != null ? <span title="Cost is unpriced, so the saving is shown in tokens.">{r.token_savings_vs_full_context_pct.toFixed(0)}% fewer tokens</span> : <NA why={r.kind === "full_context" ? "This is the full-context baseline." : "No full-context run to compare with."} />}
                        </td>
                        <td className="num px-3 py-3">{r.savings_vs_no_rag ? `${inr(r.savings_vs_no_rag.inr, 0)} (${r.savings_vs_no_rag.pct.toFixed(0)}%)` : <NA why={r.kind === "no_rag" ? "This is the no-RAG baseline." : "No priced no-RAG run to compare with."} />}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="px-5 py-3 text-xs text-subtle">Savings are per month at {num(q.data.monthly_conversations)} conversations. One-time index cost is listed below.</p>
          </Panel>

          <div className="grid gap-6 min-[1100px]:grid-cols-2">
            <Panel title="Retrieval latency">
              <BarChart
                title="Retrieval time per turn (ms)"
                missing="n/a"
                fmt={(v) => `${Math.round(v)} ms`}
                bars={rows.filter((r) => r.run_id).map((r) => ({ label: r.label, values: [{ name: "p50", value: r.latency_ms?.retrieval_p50, tone: "var(--accent)" }, { name: "p95", value: r.latency_ms?.retrieval_p95, tone: "var(--fg-muted)" }] }))}
              />
            </Panel>
            <Panel title="Cost">
              <BarChart
                title="₹ per conversation"
                missing="unpriced"
                fmt={(v) => inr(v, 4)}
                bars={rows.filter((r) => r.run_id).map((r) => ({ label: r.label, values: [{ name: "₹", value: r.cost_per_conversation_inr, tone: "var(--accent)" }] }))}
              />
            </Panel>
          </div>

          {rows.some((r) => r.index_one_time && (r.index_one_time.input_tokens > 0 || r.index_one_time.cost_inr != null)) && (
            <Panel title="One-time index cost">
              <ul className="grid gap-1 text-sm">
                {rows
                  .filter((r) => r.kind === "rag" && r.index_one_time)
                  .map((r) => (
                    <li key={r.label}>
                      <span className="font-medium">{r.label}</span>: <span className="num">{num(r.index_one_time?.input_tokens ?? 0)}</span> tokens, {r.index_one_time?.cost_inr == null ? "unpriced" : inr(r.index_one_time.cost_inr)}
                    </li>
                  ))}
              </ul>
            </Panel>
          )}
        </div>
      )}
      {q.isFetching && q.data && <span className="sr-only" role="status">Refreshing</span>}
    </>
  );
}
