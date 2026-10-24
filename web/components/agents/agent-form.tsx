"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Check, CircleX } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { LANGUAGES, LANGUAGE_LABEL } from "@/lib/format";
import { useUnsavedGuard } from "@/lib/hooks/use-unsaved-guard";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { NumberField, Repeater, Segmented, Switch, TagInput, TextAreaField, TextField } from "@/components/ui/field";
import { FormSkeleton, PageError, Strip } from "@/components/ui/states";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { ConnectionTest } from "./connection-test";

type Agent = components["schemas"]["AgentOut"];
type AgentCreate = components["schemas"]["AgentCreate"];

type Disclosure = { id: string; text: string; regex: string; within_turns: string };
type Forbidden = { id: string; text: string; regex: string };
type Tool = { name: string; description: string };
type Form = {
  name: string;
  description: string;
  languages: string[];
  adapter: AgentCreate["adapter"];
  endpoint_url: string;
  adapter_config: string;
  glass_box: boolean;
  max_call_seconds: string;
  disclosures: Disclosure[];
  forbidden: Forbidden[];
  tools: Tool[];
  bias: string[];
};

const EMPTY: Form = {
  name: "",
  description: "",
  languages: ["en-IN"],
  adapter: "audio_v1",
  endpoint_url: "",
  adapter_config: "{}",
  glass_box: false,
  max_call_seconds: "240",
  disclosures: [],
  forbidden: [],
  tools: [],
  bias: [],
};

function fromAgent(a: Agent): Form {
  return {
    name: a.name,
    description: a.description,
    languages: a.languages ?? [],
    adapter: a.adapter,
    endpoint_url: a.endpoint_url,
    adapter_config: JSON.stringify(a.adapter_config ?? {}, null, 2),
    glass_box: a.glass_box,
    max_call_seconds: String(a.max_call_seconds),
    disclosures: (a.mandatory_disclosures ?? []).map((d) => ({ id: d.id, text: d.text, regex: d.regex ?? "", within_turns: String(d.within_turns) })),
    forbidden: (a.forbidden_phrases ?? []).map((d) => ({ id: d.id, text: d.text, regex: d.regex ?? "" })),
    tools: (a.expected_tools ?? []).map((t) => ({ name: t.name, description: t.description })),
    bias: a.bias_list ?? [],
  };
}

/** Python `re` is the source of truth on the server; JS RegExp catches the common mistakes before save. */
function compileRegex(p: string): { re: RegExp | null; error: string | null } {
  if (!p) return { re: null, error: null };
  try {
    return { re: new RegExp(p, "iu"), error: null };
  } catch {
    try {
      return { re: new RegExp(p, "i"), error: null };
    } catch (e) {
      return { re: null, error: (e as Error).message.replace(/^Invalid regular expression: /, "") };
    }
  }
}

type Errors = Record<string, string>;

function validate(f: Form): Errors {
  const e: Errors = {};
  if (!f.name.trim()) e["agent-name"] = "Enter a name.";
  if (!f.description.trim()) e["agent-description"] = "Describe what the agent does. The judge and the scenario generator read this.";
  if (!f.endpoint_url.trim()) e["agent-endpoint"] = "Enter the agent's WebSocket URL.";
  else if (!/^(wss?|https?):\/\/\S+$/i.test(f.endpoint_url.trim())) e["agent-endpoint"] = "Use a full URL such as ws://host:8765/ws.";
  const secs = Number(f.max_call_seconds);
  if (!Number.isInteger(secs) || secs < 10 || secs > 1800) e["agent-max-seconds"] = "Use a whole number of seconds between 10 and 1800.";
  try {
    const cfg = JSON.parse(f.adapter_config || "{}");
    if (cfg === null || typeof cfg !== "object" || Array.isArray(cfg)) e["agent-config"] = "Adapter config must be a JSON object, for example {}.";
  } catch (err) {
    e["agent-config"] = `This is not valid JSON: ${(err as Error).message}`;
  }
  const seen = new Set<string>();
  f.disclosures.forEach((d, i) => {
    if (!d.id.trim()) e[`disc-${i}-id`] = "Enter an id.";
    else if (seen.has(d.id.trim())) e[`disc-${i}-id`] = "This id is used by another disclosure.";
    seen.add(d.id.trim());
    if (!d.text.trim()) e[`disc-${i}-text`] = "Enter the disclosure text.";
    const t = Number(d.within_turns);
    if (!Number.isInteger(t) || t < 1 || t > 50) e[`disc-${i}-turns`] = "Use a whole number from 1 to 50.";
    const { error } = compileRegex(d.regex);
    if (error) e[`disc-${i}-regex`] = `This pattern is not valid: ${error}`;
  });
  const seenF = new Set<string>();
  f.forbidden.forEach((d, i) => {
    if (!d.id.trim()) e[`forb-${i}-id`] = "Enter an id.";
    else if (seenF.has(d.id.trim())) e[`forb-${i}-id`] = "This id is used by another phrase.";
    seenF.add(d.id.trim());
    if (!d.text.trim()) e[`forb-${i}-text`] = "Enter the phrase.";
    const { error } = compileRegex(d.regex);
    if (error) e[`forb-${i}-regex`] = `This pattern is not valid: ${error}`;
  });
  f.tools.forEach((t, i) => {
    if (!t.name.trim()) e[`tool-${i}-name`] = "Enter the tool name.";
  });
  return e;
}

function toPayload(f: Form): AgentCreate {
  return {
    name: f.name.trim(),
    description: f.description.trim(),
    adapter: f.adapter,
    adapter_config: JSON.parse(f.adapter_config || "{}"),
    endpoint_url: f.endpoint_url.trim(),
    languages: f.languages,
    glass_box: f.glass_box,
    mandatory_disclosures: f.disclosures.map((d) => ({ id: d.id.trim(), text: d.text.trim(), regex: d.regex.trim() || null, within_turns: Number(d.within_turns) })),
    forbidden_phrases: f.forbidden.map((d) => ({ id: d.id.trim(), text: d.text.trim(), regex: d.regex.trim() || null })),
    expected_tools: f.tools.map((t) => ({ name: t.name.trim(), description: t.description.trim() })),
    bias_list: f.bias,
    max_call_seconds: Number(f.max_call_seconds),
  };
}

/** Regex field with a live "try a phrase" match indicator (agents spec). */
function RegexField({ idBase, value, onChange, error, label }: { idBase: string; value: string; onChange: (v: string) => void; error?: string; label: string }) {
  const [sample, setSample] = useState("");
  const { re, error: compileError } = useMemo(() => compileRegex(value), [value]);
  const matched = re && sample ? re.test(sample) : null;
  return (
    <div className="grid gap-2">
      <TextField id={`${idBase}-regex`} label={label} className="mono" value={value} onChange={(e) => onChange(e.target.value)} error={error ?? (compileError ? `This pattern is not valid: ${compileError}` : null)} help="Optional. Without a pattern the text is matched as a phrase." />
      {value && !compileError && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label={`Try a phrase against ${label.toLowerCase()}`}
            placeholder="try a phrase"
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            className="mono h-8 min-w-[160px] flex-1 rounded-sm border border-border-strong bg-surface px-2 text-sm"
          />
          <span role="status" className="inline-flex min-w-[90px] items-center gap-1 text-sm">
            {matched === null ? (
              <span className="text-subtle">no phrase yet</span>
            ) : matched ? (
              <>
                <Check size={14} strokeWidth={1.6} className="text-pass-fg" aria-hidden />
                match
              </>
            ) : (
              <>
                <CircleX size={14} strokeWidth={1.6} className="text-fail-fg" aria-hidden />
                no match
              </>
            )}
          </span>
        </div>
      )}
    </div>
  );
}

const ADAPTERS: { value: AgentCreate["adapter"]; label: string; disabled?: boolean; hint?: string }[] = [
  { value: "audio_v1", label: "audio_v1" },
  { value: "pipecat", label: "pipecat" },
  { value: "livekit", label: "livekit", disabled: true, hint: "LiveKit is not supported in this build." },
  { value: "vapi", label: "vapi", disabled: true, hint: "Vapi is not supported in this build." },
];

export function AgentForm({ agentId }: { agentId?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const search = useSearchParams();
  const isNew = !agentId;

  const agent = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => call(api.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: agentId! } } })),
    enabled: !!agentId,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });

  const [form, setForm] = useState<Form>(EMPTY);
  const [baseline, setBaseline] = useState<string>(JSON.stringify(EMPTY));
  const [errors, setErrors] = useState<Errors>({});
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const summary = useRef<HTMLDivElement>(null);
  const hydrated = useRef(false);

  useEffect(() => {
    if (agent.data && !hydrated.current) {
      hydrated.current = true;
      const f = fromAgent(agent.data);
      setForm(f);
      setBaseline(JSON.stringify(f));
    }
  }, [agent.data]);

  const dirty = JSON.stringify(form) !== baseline;
  const guard = useUnsavedGuard(dirty);
  const archived = agent.data?.archived ?? false;

  function patch(p: Partial<Form>) {
    setForm((f) => ({ ...f, ...p }));
    if (submitted) setErrors(validate({ ...form, ...p }));
  }

  const save = useMutation({
    mutationFn: (payload: AgentCreate) =>
      isNew ? call(api.POST("/api/v1/agents", { body: payload })) : call(api.PATCH("/api/v1/agents/{agent_id}", { params: { path: { agent_id: agentId! } }, body: payload })),
  });

  async function submit(then: "stay" | "test") {
    setSubmitted(true);
    setServerError(null);
    const v = validate(form);
    setErrors(v);
    const first = Object.keys(v)[0];
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
      void qc.invalidateQueries({ queryKey: ["agents"] });
      qc.setQueryData(["agent", saved.id], saved);
      toast(isNew ? `Created ${saved.name}.` : `Saved ${saved.name}.`);
      if (isNew || then === "test") router.replace(`/agents/${saved.id}${then === "test" ? "?test=1" : ""}`);
      else {
        const f = fromAgent(saved);
        setForm(f);
        setBaseline(JSON.stringify(f));
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setErrors({ "agent-name": "An agent with this name already exists." });
      setServerError(e instanceof ApiError ? e.userMessage() : "The request failed.");
    }
  }

  const archive = useMutation({
    mutationFn: () => call(api.POST("/api/v1/agents/{agent_id}/archive", { params: { path: { agent_id: agentId! } } })),
    onSuccess: (a) => {
      toast(`Archived ${a.name}.`);
      guard.release();
      void qc.invalidateQueries({ queryKey: ["agents"] });
      router.push("/agents");
    },
    onError: (e) => {
      setArchiveOpen(false);
      toast(`Could not archive: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => archive.mutate() } });
    },
  });

  const breadcrumb = (
    <Link href="/agents" className="text-sm text-accent-fg underline underline-offset-2">
      Agents
    </Link>
  );

  if (agentId && agent.isPending) {
    return (
      <>
        <PageHeader eyebrow="Agents" title="Edit agent" />
        <FormSkeleton sections={3} />
      </>
    );
  }
  if (agentId && agent.isError) {
    return (
      <>
        <PageHeader eyebrow="Agents" title="Edit agent" />
        <PageError error={agent.error} onRetry={() => void agent.refetch()} backHref="/agents" backLabel="Back to agents" />
      </>
    );
  }

  const errCount = Object.keys(errors).length;

  return (
    <>
      <PageHeader eyebrow={<>{breadcrumb} / {isNew ? "New" : agent.data?.name}</>} title={isNew ? "Add agent" : (agent.data?.name ?? "Edit agent")} description="The voice bot you want to test. Pareeksha calls it over the adapter you pick and judges the call against the rules below." />

      {archived && (
        <div className="mb-6">
          <Strip tone="warn">
            Archived on <time dateTime={agent.data!.updated_at}>{new Date(agent.data!.updated_at).toLocaleDateString("en-IN", { dateStyle: "medium" })}</time>. This agent is read-only and cannot be used in new runs.
          </Strip>
        </div>
      )}

      <form onSubmit={(e: FormEvent) => { e.preventDefault(); void submit("stay"); }} noValidate className="grid gap-6 min-[1180px]:grid-cols-[minmax(0,680px)_408px]">
        <fieldset disabled={archived} className="flex min-w-0 flex-col gap-6 border-0 p-0">
          {submitted && errCount > 0 && (
            <div ref={summary} tabIndex={-1} role="alert" className="border-l-2 border-fail bg-fail-tint px-3 py-2 text-sm">
              <p className="font-medium text-fail-fg">Fix {errCount} {errCount === 1 ? "field" : "fields"} before saving.</p>
              <ul className="mt-1 list-disc pl-5">
                {Object.entries(errors).slice(0, 5).map(([id, msg]) => (
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

          <Panel title="Basics" bodyClassName="grid gap-4">
            <TextField id="agent-name" label="Name" required value={form.name} onChange={(e) => patch({ name: e.target.value })} error={errors["agent-name"]} />
            <TextAreaField
              id="agent-description"
              label="Description"
              required
              rows={5}
              value={form.description}
              onChange={(e) => patch({ description: e.target.value })}
              error={errors["agent-description"]}
              help={`${form.description.split("\n").length} ${form.description.split("\n").length === 1 ? "line" : "lines"}. The agent's prompt text works well here.`}
            />
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-medium">Languages</legend>
              <div className="flex flex-wrap gap-4">
                {LANGUAGES.map((l) => (
                  <label key={l} className="inline-flex min-h-8 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.languages.includes(l)}
                      onChange={(e) => patch({ languages: e.target.checked ? [...form.languages, l] : form.languages.filter((x) => x !== l) })}
                      style={{ accentColor: "var(--accent)" }}
                      className="h-4 w-4"
                    />
                    {LANGUAGE_LABEL[l]} <span className="mono text-xs text-subtle">{l}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </Panel>

          <Panel title="Connection" bodyClassName="grid gap-4">
            <Segmented label="Adapter" value={form.adapter} onChange={(v) => patch({ adapter: v })} options={ADAPTERS} />
            <TextField id="agent-endpoint" label="Endpoint URL" required className="mono" placeholder="ws://host:8765/ws" value={form.endpoint_url} onChange={(e) => patch({ endpoint_url: e.target.value })} error={errors["agent-endpoint"]} />
            <TextAreaField id="agent-config" label="Adapter config (JSON)" className="mono" rows={3} spellCheck={false} value={form.adapter_config} onChange={(e) => patch({ adapter_config: e.target.value })} error={errors["agent-config"]} help="Extra settings for the adapter. Leave {} if unsure." />
            <Switch label="Glass-box" checked={form.glass_box} onChange={(v) => patch({ glass_box: v })} help="The agent sends its transcript and tool calls over the socket, and Pareeksha stores them per turn." />
            <NumberField id="agent-max-seconds" label="Max call seconds" min={10} max={1800} value={form.max_call_seconds} onChange={(e) => patch({ max_call_seconds: e.target.value })} error={errors["agent-max-seconds"]} fieldClassName="max-w-[200px]" />
          </Panel>

          <Panel title="Rules the judge checks" bodyClassName="grid gap-6">
            <Repeater<Disclosure>
              label="Mandatory disclosures"
              rows={form.disclosures}
              onChange={(disclosures) => patch({ disclosures })}
              blank={() => ({ id: "", text: "", regex: "", within_turns: "3" })}
              addLabel="Add disclosure"
              emptyText="No mandatory disclosures. Add one if the agent must say something early, such as that the call is recorded."
              render={(d, up, i) => (
                <>
                  <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
                    <TextField id={`disc-${i}-id`} label="Id" className="mono" value={d.id} onChange={(e) => up({ id: e.target.value })} error={errors[`disc-${i}-id`]} />
                    <NumberField id={`disc-${i}-turns`} label="Within turns" min={1} value={d.within_turns} onChange={(e) => up({ within_turns: e.target.value })} error={errors[`disc-${i}-turns`]} />
                  </div>
                  <TextField id={`disc-${i}-text`} label="Text" value={d.text} onChange={(e) => up({ text: e.target.value })} error={errors[`disc-${i}-text`]} />
                  <RegexField idBase={`disc-${i}`} label="Regex" value={d.regex} onChange={(regex) => up({ regex })} error={errors[`disc-${i}-regex`]} />
                </>
              )}
            />
            <Repeater<Forbidden>
              label="Forbidden phrases"
              rows={form.forbidden}
              onChange={(forbidden) => patch({ forbidden })}
              blank={() => ({ id: "", text: "", regex: "" })}
              addLabel="Add forbidden phrase"
              emptyText="No forbidden phrases."
              render={(d, up, i) => (
                <>
                  <TextField id={`forb-${i}-id`} label="Id" className="mono" value={d.id} onChange={(e) => up({ id: e.target.value })} error={errors[`forb-${i}-id`]} />
                  <TextField id={`forb-${i}-text`} label="Text" value={d.text} onChange={(e) => up({ text: e.target.value })} error={errors[`forb-${i}-text`]} />
                  <RegexField idBase={`forb-${i}`} label="Regex" value={d.regex} onChange={(regex) => up({ regex })} error={errors[`forb-${i}-regex`]} />
                </>
              )}
            />
            <Repeater<Tool>
              label="Expected tools"
              rows={form.tools}
              onChange={(tools) => patch({ tools })}
              blank={() => ({ name: "", description: "" })}
              addLabel="Add tool"
              emptyText="No expected tools."
              render={(t, up, i) => (
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField id={`tool-${i}-name`} label="Name" className="mono" value={t.name} onChange={(e) => up({ name: e.target.value })} error={errors[`tool-${i}-name`]} />
                  <TextField id={`tool-${i}-desc`} label="Description" value={t.description} onChange={(e) => up({ description: e.target.value })} />
                </div>
              )}
            />
            <TagInput label="Bias list" value={form.bias} onChange={(bias) => patch({ bias })} placeholder="Add a word and press Enter" help="Words the speech recogniser should expect, such as product names." />
          </Panel>

          {!isNew && !archived && (
            <Panel title="Danger zone">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="max-w-[48ch] text-sm text-muted">Archived agents disappear from run creation but keep their history.</p>
                <Button variant="destructive" onClick={() => setArchiveOpen(true)}>
                  <Archive size={14} strokeWidth={1.6} aria-hidden />
                  Archive agent
                </Button>
              </div>
            </Panel>
          )}

          {!archived && (
            <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 border-t border-border bg-canvas px-1 py-3">
              <Button type="submit" variant="primary" loading={save.isPending}>
                {isNew ? "Create agent" : "Save changes"}
              </Button>
              <Button disabled={save.isPending} onClick={() => void submit("test")}>
                Save and test
              </Button>
              <Link href="/agents" className="inline-flex h-8 items-center px-3 text-sm text-muted hover:text-fg">
                Cancel
              </Link>
              {dirty && <span className="text-xs text-subtle">Unsaved changes</span>}
            </div>
          )}
        </fieldset>

        <aside className="min-w-0 min-[1180px]:sticky min-[1180px]:top-16 min-[1180px]:self-start">
          <ConnectionTest agentId={agentId ?? null} settingsKey={JSON.stringify(form)} autoRun={search.get("test") === "1"} />
        </aside>
      </form>

      <ConfirmDialog
        open={archiveOpen}
        onClose={() => setArchiveOpen(false)}
        title={`Archive ${agent.data?.name ?? "agent"}?`}
        body="Archived agents disappear from run creation but keep their history."
        confirmLabel="Archive agent"
        busy={archive.isPending}
        onConfirm={() => archive.mutate()}
      />
      {guard.dialog}
    </>
  );
}
