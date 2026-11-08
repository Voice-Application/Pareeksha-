"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPricing, putPricing, ragErrorMessage, type PriceIn, type Pricing } from "@/lib/api/rag";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { controlClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

type Row = { kind: PriceIn["kind"]; provider: string; model: string; priced: boolean };
const key = (r: Pick<Row, "kind" | "provider" | "model">) => `${r.kind}|${r.provider}|${r.model}`;

function rowsOf(p: Pricing): { rows: Row[]; init: Record<string, { in: string; out: string }> } {
  const rows: Row[] = [];
  const init: Record<string, { in: string; out: string }> = {};
  for (const x of p.prices ?? []) {
    rows.push({ kind: x.kind, provider: x.provider, model: x.model, priced: true });
    init[key(x)] = { in: String(x.input_per_m_inr), out: x.output_per_m_inr == null ? "" : String(x.output_per_m_inr) };
  }
  for (const x of p.unpriced ?? []) {
    rows.push({ kind: x.kind, provider: x.provider, model: x.model, priced: false });
    init[key(x)] = { in: "", out: "" };
  }
  return { rows, init };
}

export function PricingPage() {
  const q = useQuery({ queryKey: ["pricing"], queryFn: getPricing });
  return (
    <>
      <PageHeader
        title="Pricing"
        description="Prices you enter, in rupees per 1 million tokens. Local models cost 0. Pareeksha ships no list prices, so a model without one shows tokens in the RAG report but no cost."
      />
      <Panel title="Models" bodyClassName="p-0">
        {q.isPending && <TableSkeleton rows={3} label="Loading prices" />}
        {q.isError && (
          <div className="p-5">
            <ErrorPanel error={q.error} what="pricing" onRetry={() => void q.refetch()} />
          </div>
        )}
        {q.isSuccess && <PriceTable key={q.dataUpdatedAt} data={q.data} />}
      </Panel>
    </>
  );
}

function PriceTable({ data }: { data: Pricing }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { rows, init } = rowsOf(data);
  const [vals, setVals] = useState(init);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (body: PriceIn[]) => putPricing(body),
    onSuccess: () => {
      toast("Prices saved.");
      void qc.invalidateQueries({ queryKey: ["pricing"] });
    },
    onError: (e) => setServerError(ragErrorMessage(e)),
  });

  function submit(ev: FormEvent) {
    ev.preventDefault();
    setServerError(null);
    const errs: Record<string, string> = {};
    const body: PriceIn[] = [];
    for (const r of rows) {
      const v = vals[key(r)];
      if (v.in.trim() === "" && v.out.trim() === "") continue;
      const input = Number(v.in);
      const output = v.out.trim() === "" ? null : Number(v.out);
      if (v.in.trim() === "" || !Number.isFinite(input) || input < 0) errs[key(r)] = "Enter the input price as a number, 0 or more.";
      else if (output !== null && (!Number.isFinite(output) || output < 0)) errs[key(r)] = "Enter the output price as a number, 0 or more, or leave it empty.";
      else body.push({ kind: r.kind, provider: r.provider, model: r.model, input_per_m_inr: input, output_per_m_inr: output });
    }
    setErrors(errs);
    if (Object.keys(errs).length) return;
    save.mutate(body);
  }

  if (rows.length === 0) return <p className="p-5 text-sm text-muted">No models used yet. Models appear here once a run or an index uses them.</p>;
  return (
    <form onSubmit={submit} noValidate aria-label="Prices" className="grid gap-4 pb-5">
      <div className="overflow-x-auto">
        <table className="rt">
          <caption className="sr-only">Prices per 1 million tokens, in rupees</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Kind</th>
              <th scope="col">Input ₹ / 1M</th>
              <th scope="col">Output ₹ / 1M</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const k = key(r);
              const err = errors[k];
              const set = (p: Partial<{ in: string; out: string }>) => setVals((v) => ({ ...v, [k]: { ...v[k], ...p } }));
              return (
                <tr key={k}>
                  <td data-label="">
                    <span className="mono break-all">{r.provider} / {r.model}</span>
                  </td>
                  <td data-label="Kind" className="text-muted">
                    {r.kind}
                  </td>
                  <td data-label="Input ₹ / 1M">
                    <input
                      aria-label={`Input price for ${r.model}`}
                      aria-invalid={err ? true : undefined}
                      aria-describedby={err ? `price-err-${i}` : undefined}
                      inputMode="decimal"
                      className={cn(controlClass, "mono w-28")}
                      value={vals[k].in}
                      onChange={(e) => set({ in: e.target.value })}
                    />
                  </td>
                  <td data-label="Output ₹ / 1M">
                    <input aria-label={`Output price for ${r.model}`} aria-invalid={err ? true : undefined} inputMode="decimal" className={cn(controlClass, "mono w-28")} value={vals[k].out} onChange={(e) => set({ out: e.target.value })} />
                  </td>
                  <td data-label="Status">
                    {err ? (
                      <span id={`price-err-${i}`} className="text-xs text-fail-fg">
                        {err}
                      </span>
                    ) : r.priced ? (
                      <span className="text-muted">priced</span>
                    ) : (
                      <span className="text-warn-fg">no price</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 px-5">
        {serverError && <Strip tone="error">Could not save prices. {serverError}</Strip>}
        <div>
          <Button type="submit" variant="primary" loading={save.isPending}>
            Save prices
          </Button>
        </div>
      </div>
    </form>
  );
}
