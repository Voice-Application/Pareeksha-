"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, CircleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { LANGUAGE_LABEL } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorPanel, Skeleton, Strip, TableSkeleton } from "@/components/ui/states";
import { NumberField, Switch, TextField } from "@/components/ui/field";
import { ConfirmDialog } from "@/components/ui/overlay";
import { Meter } from "@/components/ui/measure";
import { cn } from "@/lib/utils";

const STEPS = ["Agent", "Scenarios", "Callers", "Lines", "Review"] as const;
type StepName = (typeof STEPS)[number];

const csv = (v: string) => (v ? v.split(",").filter(Boolean) : []);
const inr = (n: number | null | undefined) => (n === null || n === undefined ? "-" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: n % 1 ? 2 : 0 })}`);

function PickTable<T extends { id: string }>({
  rows,
  picked,
  onChange,
  cols,
  label,
}: {
  rows: T[];
  picked: string[];
  onChange: (ids: string[]) => void;
  cols: { header: string; cell: (r: T) => React.ReactNode; mono?: boolean }[];
  label: string;
}) {
  const all = rows.length > 0 && rows.every((r) => picked.includes(r.id));
  return (
    <div className="overflow-x-auto">
      <table className="rt">
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr>
            <th scope="col" className="w-10">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--accent)]"
                aria-label={`Select all ${label.toLowerCase()}`}
                checked={all}
                onChange={() => onChange(all ? [] : rows.map((r) => r.id))}
              />
            </th>
            {cols.map((c) => (
              <th key={c.header} scope="col">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td data-label="">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[var(--accent)]"
                  checked={picked.includes(r.id)}
                  aria-label={`Select ${cols[0].cell(r) as string}`}
                  onChange={() => onChange(picked.includes(r.id) ? picked.filter((x) => x !== r.id) : [...picked, r.id])}
                />
              </td>
              {cols.map((c, i) => (
                <td key={c.header} data-label={i === 0 ? "" : c.header} className={c.mono ? "mono" : undefined}>
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RunWizardSkeleton() {
  return (
    <>
      <PageHeader title="New run" />
      <Panel bodyClassName="p-0">
        <TableSkeleton rows={6} label="Loading" />
      </Panel>
    </>
  );
}

export function RunWizard() {
  const url = useUrlState();
  const router = useRouter();
  const agentId = url.get("agent");
  // Selections are local state first (instant checkbox feedback) and mirrored into the URL for deep links.
  const [sel, setSel] = useState({ s: csv(url.get("s")), p: csv(url.get("p")), l: csv(url.get("l")) });
  const scenarioIds = sel.s;
  const personaIds = sel.p;
  const lineIds = sel.l;
  const [step, setStep] = useState<StepName>(() => STEPS.find((s) => s.toLowerCase() === url.get("step")) ?? "Agent");
  const [name, setName] = useState("");
  const [repeats, setRepeats] = useState(1);
  const [concurrency, setConcurrency] = useState(3);
  const [seed, setSeed] = useState(7);
  const [dry, setDry] = useState(false);
  const [overBudget, setOverBudget] = useState<{ estimate?: number; remaining?: number } | null>(null);
  const [confirmOver, setConfirmOver] = useState(false);

  const agents = useQuery({ queryKey: ["agents", "wizard"], queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 200 } } })) });
  const scenarios = useQuery({
    queryKey: ["scenarios", "wizard", agentId],
    enabled: !!agentId,
    queryFn: () => call(api.GET("/api/v1/scenarios", { params: { query: { agent_id: agentId, limit: 200 } } })),
  });
  const personas = useQuery({ queryKey: ["personas", "wizard"], queryFn: () => call(api.GET("/api/v1/personas", { params: { query: { limit: 200 } } })) });
  const lines = useQuery({ queryKey: ["noise", "wizard"], queryFn: () => call(api.GET("/api/v1/noise-profiles", { params: { query: { limit: 200 } } })) });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => call(api.GET("/api/v1/usage")) });

  const agent = agents.data?.items?.find((a) => a.id === agentId);
  const valid = !!agentId && scenarioIds.length > 0 && personaIds.length > 0 && lineIds.length > 0;
  const matrix = scenarioIds.length * personaIds.length * lineIds.length * repeats;

  const sCsv = sel.s.join(",");
  const pCsv = sel.p.join(",");
  const lCsv = sel.l.join(",");
  const body = useMemo(
    () => ({
      agent_id: agentId,
      name: name || `Run ${new Date().toISOString().slice(0, 10)}`,
      kind: dry ? ("dry_run" as const) : ("matrix" as const),
      scenario_ids: csv(sCsv),
      persona_ids: csv(pCsv),
      noise_profile_ids: csv(lCsv),
      repeats,
      config: { max_concurrency: concurrency, seed, dry_run: dry },
      confirm_over_budget: false,
    }),
    [agentId, name, dry, sCsv, pCsv, lCsv, repeats, concurrency, seed],
  );

  const estimate = useQuery({
    queryKey: ["run-estimate", body],
    enabled: valid,
    retry: false,
    queryFn: () => call(api.POST("/api/v1/runs:estimate", { body: body as never })),
  });

  const create = useMutation({
    mutationFn: (over: boolean) => call(api.POST("/api/v1/runs", { body: { ...body, confirm_over_budget: over } as never })),
    onSuccess: (r) => router.push(`/runs/${r.id}`),
    onError: (e) => {
      if (e instanceof ApiError && e.status === 402) {
        const d = e.details as { estimate?: { est_cost?: number }; remaining_budget?: number };
        setOverBudget({ estimate: d.estimate?.est_cost, remaining: d.remaining_budget });
      }
    },
  });

  // First agent preselected when exactly one is available (keeps the common path short).
  useEffect(() => {
    if (!agentId && (agents.data?.items ?? []).filter((a) => !a.archived).length === 1) url.set({ agent: agents.data!.items.find((a) => !a.archived)!.id });
  }, [agents.data, agentId, url]);

  const setIds = (key: "s" | "p" | "l", ids: string[]) => {
    setSel((cur) => ({ ...cur, [key]: ids }));
    url.set({ [key]: ids.join(",") || null });
  };
  const reasons = [!agentId && "Select an agent", agentId && !scenarioIds.length && "Select at least one scenario", !personaIds.length && "Select at least one persona", !lineIds.length && "Select at least one noise profile"].filter(Boolean) as string[];
  const counts: Record<StepName, string> = { Agent: agent?.name ?? "", Scenarios: scenarioIds.length ? `${scenarioIds.length} selected` : "", Callers: personaIds.length ? `${personaIds.length} selected` : "", Lines: lineIds.length ? `${lineIds.length} selected` : "", Review: "" };
  const done: Record<StepName, boolean> = { Agent: !!agentId, Scenarios: scenarioIds.length > 0, Callers: personaIds.length > 0, Lines: lineIds.length > 0, Review: valid };

  const est = estimate.data;
  const remaining = est?.remaining_budget ?? usage.data?.remaining_budget;
  const budgetErr = overBudget ?? (est?.over_budget ? { estimate: est.estimate.est_cost, remaining: est.remaining_budget ?? undefined } : null);

  function stepBody() {
    if (step === "Agent") {
      if (agents.isPending) return <TableSkeleton rows={3} />;
      if (agents.isError) return <ErrorPanel error={agents.error} what="agents" onRetry={() => void agents.refetch()} />;
      const items = (agents.data.items ?? []).filter((a) => !a.archived);
      if (!items.length) return <EmptyState icon={Check} title="No agents yet" body="An agent is the voice bot you want to test." action={<Link className="text-accent-fg underline" href="/agents/new" target="_blank">Add an agent</Link>} />;
      return (
        <fieldset>
          <legend className="sr-only">Agent under test</legend>
          <ul className="divide-y divide-border">
            {items.map((a) => (
              <li key={a.id}>
                <label className="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-hover">
                  <input type="radio" name="agent" className="mt-1 accent-[var(--accent)]" checked={agentId === a.id} onChange={() => { setSel((c) => ({ ...c, s: [] })); url.set({ agent: a.id, s: null }); }} />
                  <span className="min-w-0">
                    <span className="block font-medium">{a.name}</span>
                    <span className="mono block text-xs text-muted">
                      {a.adapter} · {(a.languages ?? []).map((l) => l.split("-")[0]).join(" ") || "no languages"}
                      {a.glass_box ? " · glass-box" : ""}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      );
    }
    if (step === "Scenarios") {
      if (!agentId) return <p className="p-4 text-sm text-muted">Choose an agent first.</p>;
      if (scenarios.isPending) return <TableSkeleton rows={4} />;
      if (scenarios.isError) return <ErrorPanel error={scenarios.error} what="scenarios" onRetry={() => void scenarios.refetch()} />;
      if (!(scenarios.data.items ?? []).length) return <EmptyState icon={Check} title="No scenarios for this agent" body="A scenario is what the caller wants and how the call should end." action={<Link className="text-accent-fg underline" href="/scenarios/new" target="_blank">Create a scenario</Link>} />;
      return (
        <PickTable
          label="Scenarios"
          rows={scenarios.data.items ?? []}
          picked={scenarioIds}
          onChange={(ids) => setIds("s", ids)}
          cols={[
            { header: "Title", cell: (r) => r.title },
            { header: "Source", cell: (r) => <Chip>{r.source}</Chip> },
            { header: "Max turns", mono: true, cell: (r) => r.max_turns },
          ]}
        />
      );
    }
    if (step === "Callers") {
      if (personas.isPending) return <TableSkeleton rows={4} />;
      if (personas.isError) return <ErrorPanel error={personas.error} what="personas" onRetry={() => void personas.refetch()} />;
      if (!(personas.data.items ?? []).length) return <EmptyState icon={Check} title="No personas" body="A persona is how the synthetic caller sounds and behaves." action={<Link className="text-accent-fg underline" href="/personas" target="_blank">Create a persona</Link>} />;
      return (
        <PickTable
          label="Personas"
          rows={personas.data.items ?? []}
          picked={personaIds}
          onChange={(ids) => setIds("p", ids)}
          cols={[
            { header: "Name", cell: (r) => r.name },
            {
              header: "Language",
              cell: (r) => (
                <span className="inline-flex items-center gap-2">
                  {LANGUAGE_LABEL[r.language] ?? r.language}
                  {agent && agent.languages && !agent.languages.includes(r.language) && (
                    <span className="inline-flex items-center gap-1 text-xs text-warn-fg" title={`Agent does not list ${r.language}`}>
                      <CircleAlert size={12} strokeWidth={1.6} aria-hidden />
                      not in agent languages
                    </span>
                  )}
                </span>
              ),
            },
            { header: "Emotion", cell: (r) => r.emotion },
            { header: "Mix", cell: (r) => r.code_mix_style },
          ]}
        />
      );
    }
    if (step === "Lines") {
      if (lines.isPending) return <TableSkeleton rows={4} />;
      if (lines.isError) return <ErrorPanel error={lines.error} what="noise profiles" onRetry={() => void lines.refetch()} />;
      const items = lines.data.items ?? [];
      const preset = () => {
        const pick = ["clean", "street", "market"].map((k) => items.find((n) => n.name.toLowerCase().includes(k))?.id).filter(Boolean) as string[];
        setIds("l", pick);
      };
      return (
        <>
          <div className="flex items-center justify-between border-b border-border px-4 py-2 text-sm">
            <span className="text-muted">Each line is a simulated phone connection.</span>
            <Button onClick={preset}>Clean + street + market</Button>
          </div>
          <PickTable
            label="Noise profiles"
            rows={items}
            picked={lineIds}
            onChange={(ids) => setIds("l", ids)}
            cols={[
              { header: "Name", cell: (r) => r.name },
              { header: "Rate", mono: true, cell: (r) => `${r.sample_rate / 1000} kHz` },
              { header: "Codec", mono: true, cell: (r) => r.codec },
              {
                header: "SNR",
                cell: (r) => (r.snr_db == null ? <span className="text-subtle">-</span> : <span className="mono">{r.snr_db} dB</span>),
              },
            ]}
          />
        </>
      );
    }
    return (
      <div className="flex max-w-[520px] flex-col gap-4 p-4">
        <TextField label="Run name" help="Shown in the runs list." placeholder={`Run ${new Date().toISOString().slice(0, 10)}`} value={name} onChange={(e) => setName(e.target.value)} />
        <div className="grid grid-cols-3 gap-3 max-[560px]:grid-cols-1">
          <NumberField label="Repeats" help="1 to 5" min={1} max={5} value={repeats} onChange={(e) => setRepeats(Math.max(1, Math.min(5, Number(e.target.value) || 1)))} />
          <NumberField label="Concurrency" help="Per-run cap, 1 to 5" min={1} max={5} value={concurrency} onChange={(e) => setConcurrency(Math.max(1, Math.min(5, Number(e.target.value) || 1)))} />
          <NumberField label="Seed" help="Same seed, same first utterance and noise" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} />
        </div>
        <Switch
          label="Dry run"
          checked={dry}
          onChange={setDry}
          disabled={!agent?.glass_box}
          help={agent?.glass_box ? "Text only. Skips TTS and STT. Costs no Gnani credits." : "Needs a glass-box agent. This agent does not declare glass-box mode."}
        />
      </div>
    );
  }

  return (
    <>
      <PageHeader eyebrow="Evaluate" title="New run" description="Choose the matrix of scenarios, callers and phone lines. The summary shows its size and cost before anything starts." />
      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[200px_minmax(0,1fr)_380px] min-[860px]:grid-cols-[200px_minmax(0,1fr)] max-[860px]:grid-cols-1">
        <nav aria-label="Run steps" className="rounded-md border border-border bg-surface p-1 max-[860px]:flex max-[860px]:overflow-x-auto">
          <ol className="contents">
            {STEPS.map((s, i) => (
              <li key={s} className="max-[860px]:shrink-0">
                <button
                  type="button"
                  aria-current={step === s ? "step" : undefined}
                  onClick={() => setStep(s)}
                  className={cn("flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-sm hover:bg-hover", step === s && "bg-selected font-medium")}
                >
                  <span className={cn("mono flex h-5 w-5 shrink-0 items-center justify-center rounded-xs border text-xs", done[s] ? "border-pass bg-pass-tint text-pass-fg" : "border-border-strong text-muted")}>
                    {done[s] ? <Check size={12} strokeWidth={2} aria-label="complete" /> : i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="block">{s}</span>
                    {counts[s] && <span className="block truncate text-xs text-subtle">{counts[s]}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <Panel
          title={step === "Callers" ? "Callers (personas)" : step === "Lines" ? "Phone lines (noise profiles)" : step === "Review" ? "Review and options" : step}
          bodyClassName="p-0"
          aux={
            <>
              {STEPS.indexOf(step) > 0 && <Button onClick={() => setStep(STEPS[STEPS.indexOf(step) - 1])}>Back</Button>}
              {STEPS.indexOf(step) < STEPS.length - 1 && (
                <Button variant="primary" onClick={() => setStep(STEPS[STEPS.indexOf(step) + 1])}>
                  Next
                </Button>
              )}
            </>
          }
        >
          {stepBody()}
        </Panel>

        <aside aria-label="Run summary" className="sticky top-4 rounded-md border border-border bg-surface min-[860px]:max-[1180px]:col-span-2 max-[1180px]:static">
          <div className="border-b border-border p-4">
            <p className="eyebrow mb-1">Matrix</p>
            <p className="mono text-sm text-muted">
              {scenarioIds.length} × {personaIds.length} × {lineIds.length} × {repeats}
            </p>
            <p className="mono display text-2xl font-semibold" aria-label={`${matrix} calls`}>
              {matrix} <span className="text-md font-normal text-muted">calls</span>
            </p>
            {matrix > 60 && (
              <p className="mt-2 flex items-start gap-1.5 text-xs text-warn-fg">
                <CircleAlert size={14} strokeWidth={1.6} className="mt-0.5 shrink-0" aria-hidden />
                Large run: about {Math.ceil((matrix * 1.5) / concurrency)} min at concurrency {concurrency} (estimate).
              </p>
            )}
          </div>
          <div className="border-b border-border p-4">
            <p className="eyebrow mb-2">Estimated cost</p>
            {!valid ? (
              <p className="text-sm text-subtle">Pick at least one of each to see the cost.</p>
            ) : estimate.isPending ? (
              <Skeleton className="h-5 w-32" />
            ) : estimate.isError ? (
              <p className="text-sm text-muted">Cost estimate unavailable. It appears after you create the run.</p>
            ) : (
              <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted">TTS audio</dt>
                <dd className="mono text-right">{Math.round(est!.estimate.tts_seconds)} s</dd>
                <dt className="text-muted">STT audio</dt>
                <dd className="mono text-right">{Math.round(est!.estimate.stt_seconds)} s</dd>
                <dt className="text-muted">Judge calls</dt>
                <dd className="mono text-right">{est!.estimate.judge_calls}</dd>
                <dt className="text-muted">Caller LLM calls</dt>
                <dd className="mono text-right">{est!.estimate.caller_llm_calls}</dd>
                <dt className="border-t border-border pt-1 font-medium">Total</dt>
                <dd className="mono border-t border-border pt-1 text-right text-md font-medium">{est!.estimate.est_cost === 0 && est!.estimate.tts_seconds > 0 ? <span className="text-sm font-normal text-subtle" title="The COST_* rates are not set in the API environment, so the total cannot be priced.">rates not set</span> : inr(est!.estimate.est_cost)}</dd>
              </dl>
            )}
            {remaining !== null && remaining !== undefined && (
              <div className="mt-3 flex items-center justify-between gap-2 text-sm">
                <span className="text-muted">Budget left</span>
                <span className="mono">{inr(remaining)}</span>
              </div>
            )}
            {est && remaining ? <div className="mt-1"><Meter value={Math.min(100, (est.estimate.est_cost / remaining) * 100)} passLine={null} width="100%" label="Estimate against remaining budget" /></div> : null}
          </div>
          <div className="flex flex-col gap-3 p-4">
            {budgetErr && (
              <Strip tone="warn">
                <p>
                  Estimated {inr(budgetErr.estimate)} exceeds the remaining {inr(budgetErr.remaining)}.
                </p>
                <div className="mt-2 flex gap-2">
                  <Button onClick={() => setStep("Scenarios")}>Reduce the matrix</Button>
                  <Button variant="destructive" onClick={() => setConfirmOver(true)}>
                    Run anyway
                  </Button>
                </div>
              </Strip>
            )}
            {create.isError && !(create.error instanceof ApiError && create.error.status === 402) && (
              <Strip tone="error" onRetry={() => create.mutate(false)}>
                {create.error instanceof ApiError ? create.error.userMessage() : "The run could not be created."}
              </Strip>
            )}
            <Button variant="primary" className="w-full justify-center" disabled={!valid || !!budgetErr} loading={create.isPending && !confirmOver} onClick={() => create.mutate(false)}>
              Create run
            </Button>
            {reasons.length > 0 && <p className="text-xs text-subtle">{reasons[0]}.</p>}
          </div>
        </aside>
      </div>
      <ConfirmDialog
        open={confirmOver}
        onClose={() => setConfirmOver(false)}
        title="Run over budget"
        body={`Estimated ${inr(budgetErr?.estimate)} exceeds the remaining ${inr(budgetErr?.remaining)}. Create the run anyway?`}
        confirmLabel="Run anyway"
        busy={create.isPending}
        onConfirm={() => create.mutate(true)}
      />
    </>
  );
}
