"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { useAgentOptions } from "@/lib/hooks/use-agents";
import { useUnsavedGuard } from "@/lib/hooks/use-unsaved-guard";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { KeyValueList, NumberField, SelectField, Switch, TagInput, TextAreaField, TextField } from "@/components/ui/field";
import { FormSkeleton, PageError, Strip } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { TAG_SUGGESTIONS } from "./scenarios-list";

type Scenario = components["schemas"]["ScenarioOut"];
type ScenarioCreate = components["schemas"]["ScenarioCreate"];

type ToolRow = { name: string; args?: unknown };
type Form = {
  title: string;
  agent_id: string;
  caller_goal: string;
  fixtures: { key: string; value: string }[];
  reveal_rules: string;
  success_criteria: string;
  must_say: string[];
  must_not_say: string[];
  tools: ToolRow[];
  ordered: boolean;
  caller_speaks_first: boolean;
  max_turns: string;
  tags: string[];
};

const EMPTY: Form = {
  title: "",
  agent_id: "",
  caller_goal: "",
  fixtures: [],
  reveal_rules: "",
  success_criteria: "",
  must_say: [],
  must_not_say: [],
  tools: [],
  ordered: false,
  caller_speaks_first: false,
  max_turns: "12",
  tags: [],
};

function fromScenario(s: Scenario): Form {
  const tools = (s.expected_tool_calls ?? []).map((t) => ({ name: String(t.name ?? ""), args: t.args }));
  return {
    title: s.title,
    agent_id: s.agent_id ?? "",
    caller_goal: s.caller_goal,
    fixtures: Object.entries(s.fixtures ?? {}).map(([key, value]) => ({ key, value: typeof value === "string" ? value : JSON.stringify(value) })),
    reveal_rules: s.reveal_rules,
    success_criteria: s.success_criteria,
    must_say: s.must_say ?? [],
    must_not_say: s.must_not_say ?? [],
    tools,
    ordered: (s.expected_tool_calls ?? []).some((t) => t.order !== undefined),
    caller_speaks_first: s.caller_speaks_first,
    max_turns: String(s.max_turns),
    tags: s.tags ?? [],
  };
}

/** Fixture values are typed as the user typed them: numbers and booleans stay numbers and booleans. */
function parseValue(v: string): unknown {
  const t = v.trim();
  if (t !== "" && !Number.isNaN(Number(t)) && /^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  if (t === "true") return true;
  if (t === "false") return false;
  return v;
}

function toPayload(f: Form): ScenarioCreate {
  const fixtures: Record<string, unknown> = {};
  for (const r of f.fixtures) if (r.key.trim()) fixtures[r.key.trim()] = parseValue(r.value);
  return {
    agent_id: f.agent_id || null,
    title: f.title.trim(),
    caller_goal: f.caller_goal.trim(),
    fixtures,
    reveal_rules: f.reveal_rules.trim(),
    success_criteria: f.success_criteria.trim(),
    must_say: f.must_say,
    must_not_say: f.must_not_say,
    expected_tool_calls: f.tools.filter((t) => t.name.trim()).map((t, i) => ({ name: t.name.trim(), ...(t.args !== undefined ? { args: t.args } : {}), ...(f.ordered ? { order: i + 1 } : {}) })),
    caller_speaks_first: f.caller_speaks_first,
    max_turns: Number(f.max_turns),
    tags: f.tags,
  };
}

type Errors = Record<string, string>;
function validate(f: Form): Errors {
  const e: Errors = {};
  if (!f.title.trim()) e["sc-title"] = "Enter a title.";
  if (!f.caller_goal.trim()) e["sc-goal"] = "Write what the caller wants.";
  if (!f.success_criteria.trim()) e["sc-success"] = "Say what a good call looks like.";
  const n = Number(f.max_turns);
  if (!Number.isInteger(n) || n < 2 || n > 40) e["sc-turns"] = "Use a whole number from 2 to 40.";
  const keys = f.fixtures.map((r) => r.key.trim()).filter(Boolean);
  if (new Set(keys).size !== keys.length) e["fx-0-key"] = "Fact names must be different.";
  return e;
}

/** Non-blocking authoring warnings (scenarios spec). */
function warnings(f: Form): string[] {
  const w: string[] = [];
  if (f.success_criteria.trim().length < 20) w.push("Success criteria are shorter than 20 characters. The judge needs something to check.");
  if (f.must_not_say.length === 0) w.push("No must-not-say rule. Add one so the judge can catch the mistake you fear most.");
  const values = f.fixtures.map((r) => r.value.toLowerCase());
  const tokens = f.caller_goal.match(/[A-Z]{2,}[-\w]*\d+|\d{3,}/g) ?? [];
  const missing = tokens.filter((t) => !values.some((v) => v.includes(t.toLowerCase())));
  if (missing.length) w.push(`The caller goal mentions ${[...new Set(missing)].join(", ")}, which is not in the facts the caller knows.`);
  return w;
}

function splitCriteria(text: string): string[] {
  return text
    .split(/\n|(?<=\.)\s+/)
    .map((s) => s.trim().replace(/^[-*]\s*/, ""))
    .filter(Boolean);
}

export function ScenarioForm({ scenarioId }: { scenarioId?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const isNew = !scenarioId;
  const agents = useAgentOptions();

  const scenario = useQuery({
    queryKey: ["scenario", scenarioId],
    queryFn: () => call(api.GET("/api/v1/scenarios/{scenario_id}", { params: { path: { scenario_id: scenarioId! } } })),
    enabled: !!scenarioId,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });

  const [form, setForm] = useState<Form>(EMPTY);
  const [baseline, setBaseline] = useState(JSON.stringify(EMPTY));
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const hydrated = useRef(false);

  useEffect(() => {
    if (scenario.data && !hydrated.current) {
      hydrated.current = true;
      const f = fromScenario(scenario.data);
      setForm(f);
      setBaseline(JSON.stringify(f));
    }
  }, [scenario.data]);

  const dirty = JSON.stringify(form) !== baseline;
  const guard = useUnsavedGuard(dirty);

  const agentTools = useMemo(() => agents.data?.find((a) => a.id === form.agent_id)?.expected_tools?.map((t) => t.name) ?? [], [agents.data, form.agent_id]);
  const warn = useMemo(() => warnings(form), [form]);
  const live = validate(form);
  // Required fields are flagged on blur and on save.
  const shown = (id: string) => (submitted || touched.has(id) ? live[id] : undefined);
  const blur = (id: string) => () => setTouched((t) => new Set(t).add(id));

  function patch(p: Partial<Form>) {
    setForm((f) => ({ ...f, ...p }));
  }

  const save = useMutation({
    mutationFn: (payload: ScenarioCreate) =>
      isNew ? call(api.POST("/api/v1/scenarios", { body: payload })) : call(api.PATCH("/api/v1/scenarios/{scenario_id}", { params: { path: { scenario_id: scenarioId! } }, body: payload })),
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setServerError(null);
    const first = Object.keys(live)[0];
    if (first) {
      requestAnimationFrame(() => {
        summary.current?.focus();
        document.getElementById(first)?.focus();
      });
      return;
    }
    try {
      const saved = await save.mutateAsync(toPayload(form));
      guard.release();
      void qc.invalidateQueries({ queryKey: ["scenarios"] });
      qc.setQueryData(["scenario", saved.id], saved);
      toast(isNew ? `Created ${saved.title}.` : `Saved ${saved.title}.`);
      if (isNew) router.replace(`/scenarios/${saved.id}`);
      else {
        const f = fromScenario(saved);
        setForm(f);
        setBaseline(JSON.stringify(f));
      }
    } catch (err) {
      setServerError(err instanceof ApiError ? err.userMessage() : "The request failed.");
    }
  }

  if (scenarioId && scenario.isPending) {
    return (
      <>
        <PageHeader eyebrow="Scenarios" title="Edit scenario" />
        <FormSkeleton sections={4} />
      </>
    );
  }
  if (scenarioId && scenario.isError) {
    return (
      <>
        <PageHeader eyebrow="Scenarios" title="Edit scenario" />
        <PageError error={scenario.error} onRetry={() => void scenario.refetch()} backHref="/scenarios" backLabel="Back to scenarios" />
      </>
    );
  }

  const promoted = scenario.data?.source === "promoted" ? scenario.data : null;
  const errCount = Object.keys(live).length;

  return (
    <>
      <PageHeader
        eyebrow={
          <>
            <Link href="/scenarios" className="text-accent-fg underline underline-offset-2">
              Scenarios
            </Link>{" "}
            / {isNew ? "New" : scenario.data?.title}
          </>
        }
        title={isNew ? "New scenario" : (scenario.data?.title ?? "Edit scenario")}
        description="What the synthetic caller is trying to do. Scenarios are language-independent: the persona decides the language."
      />

      {promoted?.source_call_id && (
        <div className="mb-6">
          <Strip tone="warn">
            Promoted from call{" "}
            <Link href={`/calls/${promoted.source_call_id}`} className="mono text-accent-fg underline">
              #{promoted.source_call_id.slice(0, 8)}
            </Link>
            . You can edit the goal; the link to the source call stays.
          </Strip>
        </div>
      )}

      <form onSubmit={submit} noValidate className="grid gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
        <div className="flex min-w-0 flex-col gap-6">
          {submitted && errCount > 0 && (
            <div ref={summary} tabIndex={-1} role="alert" className="border-l-2 border-fail bg-fail-tint px-3 py-2 text-sm">
              <p className="font-medium text-fail-fg">Fix {errCount} {errCount === 1 ? "field" : "fields"} before saving.</p>
              <ul className="mt-1 list-disc pl-5">
                {Object.entries(live).map(([id, msg]) => (
                  <li key={id}>
                    <a href={`#${id}`} className="underline" onClick={(ev) => { ev.preventDefault(); document.getElementById(id)?.focus(); }}>
                      {msg}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {serverError && <Strip tone="error">Could not save. {serverError}</Strip>}

          <Panel title="Goal" bodyClassName="grid gap-4">
            <TextField id="sc-title" label="Title" required value={form.title} onChange={(e) => patch({ title: e.target.value })} onBlur={blur("sc-title")} error={shown("sc-title")} />
            <SelectField label="Agent" value={form.agent_id} onChange={(e) => patch({ agent_id: e.target.value })} help="Leave on any agent to reuse this scenario across agents.">
              <option value="">Any agent</option>
              {agents.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </SelectField>
            <TextAreaField
              id="sc-goal"
              label="Caller goal"
              required
              rows={4}
              value={form.caller_goal}
              onChange={(e) => patch({ caller_goal: e.target.value })}
              onBlur={blur("sc-goal")}
              error={shown("sc-goal")}
              help="Write what the caller wants, in English. The persona decides the language."
            />
          </Panel>

          <Panel title="Facts the caller knows" bodyClassName="grid gap-4">
            <KeyValueList label="Facts" rows={form.fixtures} onChange={(fixtures) => patch({ fixtures })} help="Synthetic facts only, such as name, loan id, amount, UTR." />
            <TextAreaField label="Reveal rules" rows={3} value={form.reveal_rules} onChange={(e) => patch({ reveal_rules: e.target.value })} help="When may the caller share each fact?" />
          </Panel>

          <Panel title="What good looks like" bodyClassName="grid gap-4">
            <TextAreaField
              id="sc-success"
              label="Success criteria"
              required
              rows={4}
              value={form.success_criteria}
              onChange={(e) => patch({ success_criteria: e.target.value })}
              onBlur={blur("sc-success")}
              error={shown("sc-success")}
              help="Plain language. One sentence per check works best."
            />
            <TagInput label="Must say" value={form.must_say} onChange={(must_say) => patch({ must_say })} placeholder="Add a phrase and press Enter" />
            <TagInput label="Must not say" value={form.must_not_say} onChange={(must_not_say) => patch({ must_not_say })} placeholder="Add a phrase and press Enter" />
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-medium">Expected tool calls</legend>
              {form.tools.length === 0 && <p className="text-sm text-subtle">None. Add the tools the agent should call during this scenario.</p>}
              {form.tools.map((t, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="mono w-5 text-xs text-subtle">{form.ordered ? i + 1 : "-"}</span>
                  {agentTools.length > 0 ? (
                    <select aria-label={`Tool ${i + 1}`} value={t.name} onChange={(e) => patch({ tools: form.tools.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} className="mono h-8 flex-1 rounded-sm border border-border-strong bg-surface px-2 text-sm">
                      <option value="">Choose a tool</option>
                      {[...new Set([...agentTools, t.name].filter(Boolean))].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input aria-label={`Tool ${i + 1}`} placeholder="tool_name" value={t.name} onChange={(e) => patch({ tools: form.tools.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} className="mono h-8 flex-1 rounded-sm border border-border-strong bg-surface px-2 text-sm" />
                  )}
                  <Button variant="ghost" icon aria-label={`Move tool ${i + 1} up`} disabled={i === 0} onClick={() => patch({ tools: swap(form.tools, i, i - 1) })}>
                    <ArrowUp size={14} strokeWidth={1.6} aria-hidden />
                  </Button>
                  <Button variant="ghost" icon aria-label={`Move tool ${i + 1} down`} disabled={i === form.tools.length - 1} onClick={() => patch({ tools: swap(form.tools, i, i + 1) })}>
                    <ArrowDown size={14} strokeWidth={1.6} aria-hidden />
                  </Button>
                  <Button variant="ghost" icon aria-label={`Remove tool ${i + 1}`} onClick={() => patch({ tools: form.tools.filter((_, j) => j !== i) })}>
                    <Trash2 size={14} strokeWidth={1.6} aria-hidden />
                  </Button>
                </div>
              ))}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Button onClick={() => patch({ tools: [...form.tools, { name: "" }] })}>
                  <Plus size={14} strokeWidth={1.6} aria-hidden />
                  Add tool
                </Button>
                <Switch label="Required order" checked={form.ordered} onChange={(ordered) => patch({ ordered })} />
              </div>
            </fieldset>
          </Panel>

          <Panel title="Limits and labels" bodyClassName="grid gap-4">
            <NumberField id="sc-turns" label="Max turns" min={2} max={40} value={form.max_turns} onChange={(e) => patch({ max_turns: e.target.value })} onBlur={blur("sc-turns")} error={shown("sc-turns")} fieldClassName="max-w-[160px]" help="2 to 40." />
            <Switch label="Caller speaks first" checked={form.caller_speaks_first} onChange={(v) => patch({ caller_speaks_first: v })} />
            <TagInput label="Tags" mono value={form.tags} onChange={(tags) => patch({ tags })} suggestions={TAG_SUGGESTIONS} placeholder="Add a tag and press Enter" />
          </Panel>

          <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 border-t border-border bg-canvas px-1 py-3">
            <Button type="submit" variant="primary" loading={save.isPending}>
              {isNew ? "Create scenario" : "Save changes"}
            </Button>
            <Link href="/scenarios" className="inline-flex h-8 items-center px-3 text-sm text-muted hover:text-fg">
              Cancel
            </Link>
            {dirty && <span className="text-xs text-subtle">Unsaved changes</span>}
          </div>
        </div>

        <aside className="min-w-0 min-[1180px]:sticky min-[1180px]:top-16 min-[1180px]:self-start">
          <Panel title="How the judge will read this" bodyClassName="grid gap-4">
            <section aria-label="Success criteria checklist">
              <h3 className="eyebrow mb-1">Success criteria</h3>
              {splitCriteria(form.success_criteria).length === 0 ? (
                <p className="text-sm text-subtle">Nothing yet.</p>
              ) : (
                <ul className="grid gap-1 text-sm">
                  {splitCriteria(form.success_criteria).map((c, i) => (
                    <li key={i} className="flex gap-2">
                      <span aria-hidden className="mt-1.5 h-3 w-3 shrink-0 rounded-xs border border-border-strong" />
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-label="Facts">
              <h3 className="eyebrow mb-1">Facts the caller knows</h3>
              {form.fixtures.filter((r) => r.key).length === 0 ? (
                <p className="text-sm text-subtle">None.</p>
              ) : (
                <table className="w-full text-sm">
                  <tbody>
                    {form.fixtures.filter((r) => r.key).map((r, i) => (
                      <tr key={i} className="border-b border-border last:border-0">
                        <th scope="row" className="mono py-1 pr-3 text-left text-xs font-normal text-muted">
                          {r.key}
                        </th>
                        <td className="mono py-1 text-xs">{r.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
            {warn.length > 0 && (
              <section aria-label="Authoring warnings">
                <h3 className="eyebrow mb-1">Warnings</h3>
                <ul className="grid gap-2">
                  {warn.map((w) => (
                    <li key={w} className="flex gap-2 border-l-2 border-warn bg-warn-tint px-3 py-2 text-sm">
                      <TriangleAlert size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-warn-fg" aria-hidden />
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </Panel>
        </aside>
      </form>
      {guard.dialog}
    </>
  );
}

function swap<T>(xs: T[], a: number, b: number): T[] {
  const n = [...xs];
  [n[a], n[b]] = [n[b], n[a]];
  return n;
}
