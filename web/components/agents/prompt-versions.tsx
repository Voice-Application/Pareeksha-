"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type TextareaHTMLAttributes } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import {
  PROVIDERS,
  activatePromptVersion,
  activeVersionId,
  createPromptVersion,
  getPromptVersion,
  listPromptVersions,
  promptErrorMessage,
  type PromptTool,
  type PromptVersion,
  type PromptVersionCreate,
  type Provider,
} from "@/lib/api/prompt-versions";
import { DEFAULT_RAG, listKnowledgeBases, type RagConfig } from "@/lib/api/rag";
import { RagConfigFields } from "@/components/rag/rag-fields";
import { collapse, hasChanges, lineDiff, type DiffLine } from "@/lib/line-diff";
import { relativeTime } from "@/lib/format";
import { useLatest } from "@/lib/hooks/use-latest";
import { useUnsavedGuard } from "@/lib/hooks/use-unsaved-guard";
import { cn } from "@/lib/utils";
import { Chip, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { Field, NumberField, SelectField, Switch, TextField } from "@/components/ui/field";
import { DataTable, type Column } from "@/components/ui/data-table";
import { ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";

const PROMPT_MAX = 100_000;
const NOTE_MAX = 500;
const TOOL_NAME = /^[A-Za-z0-9_-]{1,64}$/;
const TOOL_KEYS = new Set(["name", "description", "parameters", "mock"]);
const MOCK_KEYS = new Set(["mode", "result", "cases"]);
const MOCK_MODES = new Set(["static", "by_args", "simulated"]);

type Draft = { system_prompt: string; provider: Provider; model: string; base_url: string; temperature: string; max_tool_rounds: string; tools: string; note: string; ragOn: boolean; rag: RagConfig };
type Errors = Record<string, string>;

const BLANK: Draft = { system_prompt: "", provider: "openai", model: "", base_url: "", temperature: "0.2", max_tool_rounds: "5", tools: "[]", note: "", ragOn: false, rag: { ...DEFAULT_RAG, kb_id: "" } };

function fromVersion(v: PromptVersion): Draft {
  return {
    system_prompt: v.system_prompt,
    provider: v.provider,
    model: v.model,
    base_url: v.base_url ?? "",
    temperature: String(v.temperature),
    max_tool_rounds: String(v.max_tool_rounds),
    tools: JSON.stringify(v.tools ?? [], null, 2),
    note: "",
    ragOn: !!v.rag_config,
    rag: v.rag_config ?? { ...DEFAULT_RAG, kb_id: "" },
  };
}

const EXAMPLE_TOOL: PromptTool = {
  name: "lookup_emi",
  description: "Look up the EMI amount and due date for a loan.",
  parameters: { type: "object", properties: { loan_id: { type: "string", description: "Loan id, such as SHK-000123" } }, required: ["loan_id"] },
  mock: { mode: "static", result: { emi_amount: 4000, due_date: "2026-11-10" }, cases: [] },
};

const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x);

/** Client-side check of the PromptTool shape, so most mistakes show before the API answers 400. */
export function parseTools(text: string): { tools: PromptTool[] | null; issues: string[] } {
  let raw: unknown;
  try {
    raw = JSON.parse(text.trim() || "[]");
  } catch (e) {
    return { tools: null, issues: [`This is not valid JSON: ${(e as Error).message}`] };
  }
  if (!Array.isArray(raw)) return { tools: null, issues: ["Tools must be a JSON array, for example []."] };
  const issues: string[] = [];
  if (raw.length > 64) issues.push("Use at most 64 tools.");
  const seen = new Set<string>();
  raw.forEach((t, i) => {
    const at = `Tool ${i + 1}`;
    if (!isObj(t)) {
      issues.push(`${at} must be an object.`);
      return;
    }
    const extra = Object.keys(t).filter((k) => !TOOL_KEYS.has(k));
    if (extra.length) issues.push(`${at}: unknown key ${extra.map((k) => `"${k}"`).join(", ")}. Use name, description, parameters and mock.`);
    if (typeof t.name !== "string" || !TOOL_NAME.test(t.name)) issues.push(`${at}: name must be 1 to 64 letters, digits, _ or -.`);
    else if (seen.has(t.name)) issues.push(`${at}: another tool is already named ${t.name}.`);
    else seen.add(t.name);
    if (t.description !== undefined && typeof t.description !== "string") issues.push(`${at}: description must be text.`);
    if (!isObj(t.parameters) || t.parameters.type !== "object") issues.push(`${at}: parameters must be a JSON Schema with "type": "object".`);
    if (t.mock === undefined) return;
    const m = t.mock;
    if (!isObj(m)) {
      issues.push(`${at}: mock must be an object.`);
      return;
    }
    const mExtra = Object.keys(m).filter((k) => !MOCK_KEYS.has(k));
    if (mExtra.length) issues.push(`${at}: unknown mock key ${mExtra.map((k) => `"${k}"`).join(", ")}. Use mode, result and cases.`);
    if (m.mode !== undefined && !MOCK_MODES.has(String(m.mode))) issues.push(`${at}: mock.mode must be static, by_args or simulated.`);
    if (m.result !== undefined && !isObj(m.result)) issues.push(`${at}: mock.result must be an object.`);
    if (m.cases !== undefined && (!Array.isArray(m.cases) || m.cases.some((c) => !isObj(c) || !isObj(c.when) || !isObj(c.result))))
      issues.push(`${at}: mock.cases must be a list of {"when": {...}, "result": {...}}.`);
  });
  return { tools: issues.length ? null : (raw as PromptTool[]), issues };
}

function check(d: Draft): { errors: Errors; body: PromptVersionCreate | null } {
  const e: Errors = {};
  if (!d.system_prompt.trim()) e["pv-system-prompt"] = "Paste the system prompt your agent uses.";
  else if (d.system_prompt.length > PROMPT_MAX) e["pv-system-prompt"] = `Keep the prompt under ${PROMPT_MAX.toLocaleString("en-IN")} characters.`;
  if (!d.model.trim()) e["pv-model"] = "Enter the model name, such as gpt-4o-mini.";
  else if (d.model.trim().length > 200) e["pv-model"] = "Use at most 200 characters.";
  const url = d.base_url.trim();
  if (url && !/^https?:\/\/\S+$/i.test(url)) e["pv-base-url"] = "Use a full http or https URL, such as https://llm.example.com/v1.";
  else if (!url && d.provider === "openai_compatible") e["pv-base-url"] = "OpenAI-compatible servers need a base URL.";
  const temp = Number(d.temperature);
  if (d.temperature.trim() === "" || !Number.isFinite(temp) || temp < 0 || temp > 2) e["pv-temperature"] = "Use a number from 0 to 2.";
  const rounds = Number(d.max_tool_rounds);
  if (!Number.isInteger(rounds) || rounds < 1 || rounds > 10) e["pv-max-rounds"] = "Use a whole number from 1 to 10.";
  const { tools, issues } = parseTools(d.tools);
  if (issues.length) e["pv-tools"] = issues.slice(0, 3).join(" ") + (issues.length > 3 ? ` And ${issues.length - 3} more.` : "");
  if (d.ragOn && !d.rag.kb_id) e["pv-rag-kb"] = "Choose the knowledge base this prompt retrieves from.";
  if (d.note.length > NOTE_MAX) e["pv-note"] = `Keep the note under ${NOTE_MAX} characters.`;
  if (Object.keys(e).length || !tools) return { errors: e, body: null };
  return {
    errors: e,
    body: { system_prompt: d.system_prompt, provider: d.provider, model: d.model.trim(), base_url: url || null, temperature: temp, tools, max_tool_rounds: rounds, note: d.note.trim(), rag_config: d.ragOn ? d.rag : null },
  };
}

function baseUrlHelp(p: Provider): string {
  if (p === "openai_compatible") return "The server's OpenAI-compatible endpoint, such as https://llm.example.com/v1.";
  if (p === "ollama") return "Your Ollama server. Leave empty for the default.";
  return "Leave empty to use the provider's own endpoint.";
}

/** The canonical text of everything except the prompt, so model and tool changes diff line by line too. */
function settingsText(v: PromptVersion): string {
  return [`provider: ${v.provider}`, `model: ${v.model}`, `base_url: ${v.base_url || "-"}`, `temperature: ${v.temperature}`, `max_tool_rounds: ${v.max_tool_rounds}`, `tools: ${JSON.stringify(v.tools ?? [], null, 2)}`].join("\n");
}

/** Monospace textarea with a line-number gutter. Lines do not wrap, so numbers stay aligned and match the diff. */
function CodeArea({ id, value, describedBy, invalid, className, ...rest }: { id: string; value: string; describedBy?: string; invalid?: boolean } & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const gutter = useRef<HTMLDivElement>(null);
  const count = value === "" ? 1 : value.split("\n").length;
  // The numbers sit in an absolutely positioned layer, so the gutter takes the textarea's height
  // (including manual resizes) instead of growing with the line count.
  const digits = String(count).length;
  return (
    <div
      className={cn(
        "flex overflow-hidden rounded-sm border bg-surface focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[color:var(--focus-ring)]",
        invalid ? "border-fail" : "border-border-strong",
      )}
    >
      <div aria-hidden className="mono relative shrink-0 select-none border-r border-border bg-sunken text-xs" style={{ width: `calc(${digits}ch + 1rem + 1px)` }}>
        {/* Extra bottom padding covers the textarea's horizontal scrollbar, so both reach the last line together. */}
        <div ref={gutter} className="absolute inset-0 overflow-hidden px-2 pb-6 pt-1.5 text-right leading-5 text-subtle">
          {Array.from({ length: count }, (_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
      </div>
      <textarea
        id={id}
        value={value}
        wrap="off"
        spellCheck={false}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
        className={cn("mono min-w-0 flex-1 resize-y bg-transparent px-3 py-1.5 text-sm leading-5 text-fg placeholder:text-subtle read-only:text-muted", className)}
        style={{ outline: "none" }}
        {...rest}
      />
    </div>
  );
}

const ids = (...xs: (string | false | undefined)[]) => xs.filter(Boolean).join(" ") || undefined;

export function PromptVersions({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const agent = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => call(api.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: agentId } } })),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });
  const isPrompt = agent.data?.adapter === "prompt";
  const readOnly = agent.data?.archived ?? false;
  const versions = useQuery({ queryKey: ["prompt-versions", agentId], queryFn: () => listPromptVersions(agentId), enabled: isPrompt });
  const list = useMemo(() => [...(versions.data ?? [])].sort((a, b) => b.version - a.version), [versions.data]);
  const activeId = agent.data ? activeVersionId(agent.data) : null;
  const active = list.find((v) => v.id === activeId) ?? null;

  const [draft, setDraft] = useState<Draft>(BLANK);
  const [baseline, setBaseline] = useState(JSON.stringify(BLANK));
  const [errors, setErrors] = useState<Errors>({});
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [pair, setPair] = useState<{ from: number; to: number } | null>(null);
  const hydrated = useRef(false);

  useEffect(() => {
    if (!versions.isSuccess || !agent.data || hydrated.current) return;
    hydrated.current = true;
    const start = active ?? list[0];
    const d = start ? fromVersion(start) : BLANK;
    setDraft(d);
    setBaseline(JSON.stringify(d));
  }, [versions.isSuccess, agent.data, active, list]);

  const dirty = JSON.stringify(draft) !== baseline;
  const guard = useUnsavedGuard(dirty && isPrompt);
  const editor = useLatest({ draft, baseline });

  const kbs = useQuery({ queryKey: ["knowledge-bases"], queryFn: listKnowledgeBases, enabled: isPrompt && draft.ragOn, select: (p) => p.items ?? [] });
  const view = useQuery({ queryKey: ["prompt-version", agentId, viewing], queryFn: () => getPromptVersion(agentId, viewing as number), enabled: viewing != null });

  const save = useMutation({ mutationFn: (body: PromptVersionCreate) => createPromptVersion(agentId, body) });
  const activate = useMutation({
    mutationFn: (version: number) => activatePromptVersion(agentId, version),
    onSuccess: (v) => {
      toast(`v${v.version} is now the active version.`);
      // A clean editor follows the active version; a dirty draft is the user's work and stays.
      const { draft: cur, baseline: base } = editor.current;
      if (JSON.stringify(cur) === base) {
        const d = fromVersion(v);
        setDraft(d);
        setBaseline(JSON.stringify(d));
        setResult(null);
      }
      void qc.invalidateQueries({ queryKey: ["agent", agentId] });
      void qc.invalidateQueries({ queryKey: ["prompt-versions", agentId] });
    },
    onError: (e, version) => toast(`Could not activate v${version}: ${promptErrorMessage(e)}`, { tone: "error" }),
  });

  function patch(p: Partial<Draft>) {
    const next = { ...draft, ...p };
    setDraft(next);
    setResult(null);
    if (submitted) setErrors(check(next).errors);
  }

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setSubmitted(true);
    setServerError(null);
    setResult(null);
    const { errors: v, body } = check(draft);
    setErrors(v);
    const first = Object.keys(v)[0];
    if (first || !body) {
      if (first) requestAnimationFrame(() => document.getElementById(first)?.focus());
      return;
    }
    try {
      const r = await save.mutateAsync(body);
      setResult(r.created ? `Saved v${r.version.version}. It is now the active version.` : `No changes, still v${r.version.version}.`);
      // The baseline is what was submitted. Edits made while the save was pending stay in the draft
      // (and keep it dirty); only the note, which went into this version, is cleared.
      const snapshot = draft;
      setBaseline(JSON.stringify({ ...snapshot, note: "" }));
      setDraft((cur) => (cur.note === snapshot.note ? { ...cur, note: "" } : cur));
      if (r.created) setPair(null);
      void qc.invalidateQueries({ queryKey: ["prompt-versions", agentId] });
      void qc.invalidateQueries({ queryKey: ["agent", agentId] });
    } catch (e) {
      if (e instanceof ApiError && e.code === "base_url_not_allowed") setErrors({ "pv-base-url": promptErrorMessage(e) });
      setServerError(promptErrorMessage(e));
    }
  }

  function insertExample() {
    const { issues } = parseTools(draft.tools);
    let current: PromptTool[] = [];
    try {
      const parsed: unknown = JSON.parse(draft.tools.trim() || "[]");
      if (Array.isArray(parsed)) current = parsed as PromptTool[];
      else return setErrors((e) => ({ ...e, "pv-tools": "Fix the JSON first: tools must be an array." }));
    } catch {
      return setErrors((e) => ({ ...e, "pv-tools": issues[0] ?? "Fix the JSON first." }));
    }
    const taken = new Set(current.map((t) => (isObj(t) ? t.name : "")));
    let name = EXAMPLE_TOOL.name;
    for (let n = 2; taken.has(name); n++) name = `${EXAMPLE_TOOL.name}_${n}`;
    patch({ tools: JSON.stringify([...current, { ...EXAMPLE_TOOL, name }], null, 2) });
    requestAnimationFrame(() => document.getElementById("pv-tools")?.focus());
  }

  if (!isPrompt) return null;

  const promptLines = draft.system_prompt === "" ? 0 : draft.system_prompt.split("\n").length;
  const from = pair?.from ?? list[1]?.version;
  const to = pair?.to ?? list[0]?.version;
  const fromV = list.find((v) => v.version === from);
  const toV = list.find((v) => v.version === to);

  const columns: Column<PromptVersion>[] = [
    {
      key: "version",
      header: "Version",
      cell: (v) => (
        <span className="inline-flex items-center gap-2">
          <span className="mono font-medium">v{v.version}</span>
          {v.id === activeId && (
            <Chip>
              <Check size={12} strokeWidth={1.6} aria-hidden />
              active
            </Chip>
          )}
        </span>
      ),
    },
    { key: "note", header: "Note", cell: (v) => (v.note ? <span className="line-clamp-2">{v.note}</span> : <span className="text-subtle">-</span>) },
    {
      key: "saved",
      header: "Saved",
      hidePhone: true,
      cell: (v) => (
        <time dateTime={v.created_at} title={v.created_at} className="whitespace-nowrap text-muted">
          {relativeTime(v.created_at)}
        </time>
      ),
    },
  ];

  return (
    <div className="mb-8 flex flex-col gap-6">
      <div className="grid gap-6 min-[1180px]:grid-cols-[minmax(0,680px)_408px]">
        <form onSubmit={(e) => void submit(e)} noValidate aria-label="Prompt version" className="min-w-0">
          <fieldset disabled={readOnly} className="m-0 min-w-0 border-0 p-0">
            <Panel
              title="Prompt"
              aux={active ? <span>Active: <span className="mono">v{active.version}</span></span> : versions.isSuccess ? <span>No version yet</span> : null}
              bodyClassName="grid gap-4"
            >
              {versions.isPending && <TableSkeleton rows={3} label="Loading prompt" />}
              {versions.isError && <ErrorPanel error={versions.error} what="prompt versions" onRetry={() => void versions.refetch()} />}
              {versions.isSuccess && (
                <>
                  {list.length === 0 && <p className="text-sm text-muted">Paste the system prompt your production LLM uses, pick the model and save. Every save is an immutable version you can run and compare.</p>}
                  <div className="grid gap-4 sm:grid-cols-[minmax(0,220px)_minmax(0,1fr)]">
                    <SelectField id="pv-provider" label="Provider" value={draft.provider} onChange={(e) => patch({ provider: e.target.value as Provider })}>
                      {PROVIDERS.map((p) => (
                        <option key={p.value} value={p.value}>
                          {p.label}
                        </option>
                      ))}
                    </SelectField>
                    <TextField id="pv-model" label="Model" required className="mono" placeholder="gpt-4o-mini" value={draft.model} onChange={(e) => patch({ model: e.target.value })} error={errors["pv-model"]} />
                  </div>
                  <TextField id="pv-base-url" label="Base URL" className="mono" placeholder="https://" value={draft.base_url} onChange={(e) => patch({ base_url: e.target.value })} error={errors["pv-base-url"]} help={baseUrlHelp(draft.provider)} />

                  <Field label="System prompt" id="pv-system-prompt" required error={errors["pv-system-prompt"]}>
                    <CodeArea
                      id="pv-system-prompt"
                      rows={16}
                      value={draft.system_prompt}
                      onChange={(e) => patch({ system_prompt: e.target.value })}
                      invalid={!!errors["pv-system-prompt"]}
                      describedBy={ids("pv-system-prompt-count", errors["pv-system-prompt"] && "pv-system-prompt-error")}
                      required
                    />
                    <p id="pv-system-prompt-count" className={cn("num text-xs", draft.system_prompt.length > PROMPT_MAX ? "text-fail-fg" : "text-subtle")}>
                      {draft.system_prompt.length.toLocaleString("en-IN")} of {PROMPT_MAX.toLocaleString("en-IN")} characters, {promptLines} {promptLines === 1 ? "line" : "lines"}
                    </p>
                  </Field>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <NumberField id="pv-temperature" label="Temperature" min={0} max={2} step={0.1} inputMode="decimal" value={draft.temperature} onChange={(e) => patch({ temperature: e.target.value })} error={errors["pv-temperature"]} help="0 to 2. Lower is more repeatable across runs." />
                    <NumberField id="pv-max-rounds" label="Max tool rounds" min={1} max={10} value={draft.max_tool_rounds} onChange={(e) => patch({ max_tool_rounds: e.target.value })} error={errors["pv-max-rounds"]} help="Tool calls per agent turn before the turn ends." />
                  </div>

                  <Field label="Tools (JSON)" id="pv-tools" error={errors["pv-tools"]}>
                    <CodeArea
                      id="pv-tools"
                      rows={10}
                      value={draft.tools}
                      onChange={(e) => patch({ tools: e.target.value })}
                      invalid={!!errors["pv-tools"]}
                      describedBy={ids("pv-tools-help", errors["pv-tools"] && "pv-tools-error")}
                    />
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p id="pv-tools-help" className="max-w-[52ch] text-xs text-subtle">
                        An array of tools the model can call. Each has a name, description, parameters (JSON Schema with <code className="mono">&quot;type&quot;: &quot;object&quot;</code>) and a mock: <code className="mono">static</code> result, <code className="mono">by_args</code> cases or <code className="mono">simulated</code>.
                      </p>
                      <Button className="h-8 px-3" onClick={insertExample}>
                        <Plus size={14} strokeWidth={1.6} aria-hidden />
                        Add example tool
                      </Button>
                    </div>
                  </Field>

                  <fieldset className="grid gap-4 rounded-sm border border-border p-4">
                    <legend className="px-1 text-sm font-medium">Retrieval (RAG)</legend>
                    <Switch label="Retrieve from a knowledge base" checked={draft.ragOn} onChange={(v) => patch({ ragOn: v })} help={<>Put <code className="mono">{"{{context}}"}</code> in the system prompt where the retrieved passages should go. Without it, Pareeksha adds them after the prompt under &quot;Retrieved context:&quot;.</>} />
                    {draft.ragOn && (
                      <>
                        {kbs.isError && <ErrorPanel error={kbs.error} what="knowledge bases" onRetry={() => void kbs.refetch()} />}
                        <RagConfigFields ids="pv-rag" value={draft.rag} onChange={(rag) => patch({ rag })} kbs={kbs.data ?? []} kbError={errors["pv-rag-kb"]} />
                      </>
                    )}
                  </fieldset>

                  <TextField id="pv-note" label="Version note" placeholder="What changed, for example: stricter amount confirmation" maxLength={NOTE_MAX} value={draft.note} onChange={(e) => patch({ note: e.target.value })} error={errors["pv-note"]} help="Optional. Shown in the version list." />

                  {serverError && <Strip tone="error">Could not save the version. {serverError}</Strip>}
                  {!readOnly && (
                    <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
                      <Button type="submit" variant="primary" loading={save.isPending}>
                        Save as new version
                      </Button>
                      {dirty && <span className="text-xs text-subtle">Unsaved prompt changes</span>}
                      <p role="status" aria-live="polite" className="text-sm">
                        {result}
                      </p>
                    </div>
                  )}
                </>
              )}
            </Panel>
          </fieldset>
        </form>

        <div className="flex min-w-0 flex-col gap-6 min-[1180px]:self-start">
          <Panel title="Versions" bodyClassName="p-0" aux={versions.isSuccess ? <span className="num">{list.length}</span> : null}>
            {versions.isPending && <TableSkeleton rows={3} label="Loading versions" />}
            {versions.isSuccess && list.length === 0 && <p className="px-5 pb-5 text-sm text-muted">No versions yet. Save the prompt to create v1.</p>}
            {versions.isSuccess && list.length > 0 && (
              <DataTable
                caption="Prompt versions, newest first"
                columns={columns}
                rows={list}
                rowKey={(v) => v.id}
                sort={null}
                onSort={() => undefined}
                actions={(v) => (
                  <span className="inline-flex gap-1">
                    <Button variant="ghost" className="h-8 px-2" aria-label={`View v${v.version}`} aria-pressed={viewing === v.version} onClick={() => setViewing(viewing === v.version ? null : v.version)}>
                      View
                    </Button>
                    {v.id !== activeId && !readOnly && (
                      <Button className="h-8 px-2" aria-label={`Activate v${v.version}`} loading={activate.isPending && activate.variables === v.version} onClick={() => activate.mutate(v.version)}>
                        Activate
                      </Button>
                    )}
                  </span>
                )}
              />
            )}
          </Panel>

          {viewing != null && (
            <Panel title={`Version ${viewing}`} aux={<Button variant="ghost" className="h-8 px-2" onClick={() => setViewing(null)}>Close</Button>} bodyClassName="grid gap-3">
              {view.isPending && <TableSkeleton rows={3} label={`Loading v${viewing}`} />}
              {view.isError && <ErrorPanel error={view.error} what={`v${viewing}`} onRetry={() => void view.refetch()} />}
              {view.data && (
                <>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-muted">Model</dt>
                    <dd className="mono min-w-0 break-all">
                      {view.data.provider} / {view.data.model}
                    </dd>
                    <dt className="text-muted">Temperature</dt>
                    <dd className="mono">{view.data.temperature}</dd>
                    <dt className="text-muted">Tools</dt>
                    <dd className="mono min-w-0 break-all">{(view.data.tools ?? []).map((t) => t.name).join(", ") || "-"}</dd>
                    <dt className="text-muted">Hash</dt>
                    <dd className="mono text-xs text-subtle">{view.data.content_hash.slice(0, 12)}</dd>
                  </dl>
                  <div className="flex flex-col gap-1">
                    <label htmlFor="pv-view-prompt" className="text-sm font-medium">
                      System prompt of v{view.data.version}
                    </label>
                    <CodeArea id="pv-view-prompt" rows={10} value={view.data.system_prompt} readOnly />
                  </div>
                  {!readOnly && (
                    <div>
                      <Button
                        onClick={() => {
                          setDraft(fromVersion(view.data));
                          setResult(null);
                          requestAnimationFrame(() => document.getElementById("pv-system-prompt")?.focus());
                        }}
                      >
                        Load into editor
                      </Button>
                    </div>
                  )}
                </>
              )}
            </Panel>
          )}
        </div>
      </div>

      {list.length >= 2 && fromV && toV && (
        <Panel title="Compare versions" className="min-[1180px]:max-w-[1112px]" bodyClassName="grid gap-5">
          <div className="flex flex-wrap items-end gap-3">
            <SelectField id="pv-diff-from" label="From" value={String(fromV.version)} onChange={(e) => setPair({ from: Number(e.target.value), to: toV.version })} fieldClassName="w-40">
              {list.map((v) => (
                <option key={v.id} value={v.version}>
                  v{v.version}
                  {v.id === activeId ? " (active)" : ""}
                </option>
              ))}
            </SelectField>
            <span className="pb-2 text-muted" aria-hidden>
              →
            </span>
            <SelectField id="pv-diff-to" label="To" value={String(toV.version)} onChange={(e) => setPair({ from: fromV.version, to: Number(e.target.value) })} fieldClassName="w-40">
              {list.map((v) => (
                <option key={v.id} value={v.version}>
                  v{v.version}
                  {v.id === activeId ? " (active)" : ""}
                </option>
              ))}
            </SelectField>
          </div>
          <DiffView key={`p-${fromV.id}-${toV.id}`} title="System prompt" caption={`System prompt diff, v${fromV.version} to v${toV.version}`} before={fromV.system_prompt} after={toV.system_prompt} />
          <DiffView key={`s-${fromV.id}-${toV.id}`} title="Model and tools" caption={`Model and tools diff, v${fromV.version} to v${toV.version}`} before={settingsText(fromV)} after={settingsText(toV)} />
        </Panel>
      )}
      {guard.dialog}
    </div>
  );
}

function DiffView({ title, caption, before, after }: { title: string; caption: string; before: string; after: string }) {
  const diff = useMemo(() => lineDiff(before, after), [before, after]);
  const lines = useMemo(() => (diff.tooLarge ? [] : diff.lines), [diff]);
  const rows = useMemo(() => collapse(lines, 2), [lines]);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const added = lines.filter((l) => l.kind === "add").length;
  const removed = lines.filter((l) => l.kind === "del").length;
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="num text-xs text-muted">{diff.tooLarge ? "Too large to diff" : hasChanges(lines) ? `${added} added, ${removed} removed` : "No changes"}</p>
      </div>
      {diff.tooLarge && <p className="text-sm text-muted">{diff.message}</p>}
      {hasChanges(lines) && (
        <div className="overflow-x-auto rounded-sm border border-border">
          <table className="mono w-full border-collapse text-sm leading-5">
            <caption className="sr-only">{caption}</caption>
            <thead className="sr-only">
              <tr>
                <th scope="col">Old line</th>
                <th scope="col">New line</th>
                <th scope="col">Change</th>
                <th scope="col">Text</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) =>
                r.type === "line" ? (
                  <Row key={i} l={r.line} />
                ) : open.has(i) ? (
                  r.lines.map((l, k) => <Row key={`${i}-${k}`} l={l} />)
                ) : (
                  <tr key={i} className="bg-sunken">
                    <td colSpan={4} className="px-2 py-0.5">
                      <button type="button" className="text-xs text-accent-fg underline-offset-2 hover:underline" onClick={() => setOpen((s) => new Set(s).add(i))}>
                        Show {r.lines.length} unchanged {r.lines.length === 1 ? "line" : "lines"}
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Row({ l }: { l: DiffLine }) {
  const tone = l.kind === "add" ? "bg-pass-tint" : l.kind === "del" ? "bg-fail-tint" : undefined;
  return (
    <tr data-kind={l.kind} className={tone}>
      <td className="w-10 select-none px-2 text-right align-top text-xs leading-5 text-subtle">{l.a ?? ""}</td>
      <td className="w-10 select-none px-2 text-right align-top text-xs leading-5 text-subtle">{l.b ?? ""}</td>
      <td className={cn("w-5 select-none text-center align-top", l.kind === "add" ? "text-pass-fg" : l.kind === "del" ? "text-fail-fg" : "text-subtle")}>
        <span aria-hidden>{l.kind === "add" ? "+" : l.kind === "del" ? "-" : ""}</span>
        <span className="sr-only">{l.kind === "add" ? "added" : l.kind === "del" ? "removed" : "unchanged"}</span>
      </td>
      <td className="whitespace-pre px-2 align-top">{l.text || " "}</td>
    </tr>
  );
}
