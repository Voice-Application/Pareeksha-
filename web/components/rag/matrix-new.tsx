"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { listPromptVersions } from "@/lib/api/prompt-versions";
import { DEFAULT_RAG, buildIndex, createMatrix, listKnowledgeBases, missingIndexes, ragErrorMessage, type MissingIndex, type RagConfig } from "@/lib/api/rag";
import { useAgentOptions } from "@/lib/hooks/use-agents";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { NumberField, SelectField, Switch, TextField } from "@/components/ui/field";
import { Strip } from "@/components/ui/states";
import { RagConfigFields } from "./rag-fields";

type Item = { id: string; label: string };

function CheckList({ legend, items, picked, onChange, empty, error }: { legend: string; items: Item[]; picked: string[]; onChange: (v: string[]) => void; empty: React.ReactNode; error?: string }) {
  const eid = `${legend.replace(/\s+/g, "-")}-err`;
  return (
    <fieldset className="grid gap-2" aria-describedby={error ? eid : undefined}>
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      {items.length === 0 && <p className="text-sm text-muted">{empty}</p>}
      <div className="grid max-h-56 gap-1 overflow-y-auto">
        {items.map((it) => (
          <label key={it.id} className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={picked.includes(it.id)} onChange={(e) => onChange(e.target.checked ? [...picked, it.id] : picked.filter((x) => x !== it.id))} />
            <span>{it.label}</span>
          </label>
        ))}
      </div>
      {error && (
        <p id={eid} className="text-xs text-fail-fg">
          {error}
        </p>
      )}
    </fieldset>
  );
}

function MissingRow({ kbId, m }: { kbId: string; m: MissingIndex }) {
  const build = useMutation({ mutationFn: () => buildIndex(kbId, { chunking: m.chunking, embedding: m.embedding }) });
  return (
    <li className="flex flex-wrap items-center justify-between gap-3">
      <span className="min-w-0 text-sm">
        <span className="font-medium">{m.label}</span>{" "}
        <span className="mono text-xs text-muted">
          {m.chunking.strategy} {m.chunking.size}/{m.chunking.overlap}, {m.embedding.provider} / {m.embedding.model}
        </span>
      </span>
      {build.data ? (
        <span role="status" className="text-sm">
          {build.data.created ? `Building index v${build.data.index.version}. Create the matrix again once it is ready.` : `Using existing index v${build.data.index.version} (${build.data.index.status}).`}
        </span>
      ) : (
        <Button className="h-8 px-3" aria-label={`Build index for ${m.label}`} loading={build.isPending} onClick={() => build.mutate()}>
          Build index
        </Button>
      )}
      {build.isError && <span role="alert" className="w-full text-xs text-fail-fg">{ragErrorMessage(build.error)}</span>}
    </li>
  );
}

export function MatrixNew() {
  const router = useRouter();
  const qc = useQueryClient();
  const agents = useAgentOptions();
  const promptAgents = (agents.data ?? []).filter((a) => a.adapter === "prompt" && !a.archived);
  const [agentId, setAgentId] = useState("");
  const [version, setVersion] = useState("");
  const [kbId, setKbId] = useState("");
  const [configs, setConfigs] = useState<RagConfig[]>([]);
  const [noRag, setNoRag] = useState(true);
  const [fullCtx, setFullCtx] = useState(true);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [personas, setPersonas] = useState<string[]>([]);
  const [noise, setNoise] = useState<string[]>([]);
  const [repeats, setRepeats] = useState("1");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [missing, setMissing] = useState<MissingIndex[]>([]);

  const kbs = useQuery({ queryKey: ["knowledge-bases"], queryFn: listKnowledgeBases, select: (p) => p.items ?? [] });
  const versions = useQuery({ queryKey: ["prompt-versions", agentId], queryFn: () => listPromptVersions(agentId), enabled: !!agentId });
  const scen = useQuery({ queryKey: ["scenarios", "rag-tag"], queryFn: () => call(api.GET("/api/v1/scenarios", { params: { query: { tag: "rag", limit: 200 } } })), select: (p) => p.items ?? [] });
  const pers = useQuery({ queryKey: ["personas", "all"], queryFn: () => call(api.GET("/api/v1/personas", { params: { query: { limit: 200 } } })), select: (p) => p.items ?? [] });
  const noi = useQuery({ queryKey: ["noise", "all"], queryFn: () => call(api.GET("/api/v1/noise-profiles", { params: { query: { limit: 200 } } })), select: (p) => p.items ?? [] });
  const kb = kbs.data?.find((k) => k.id === kbId);
  const kbList = useMemo(() => (kb ? [kb] : []), [kb]);

  function pickKb(id: string) {
    setKbId(id);
    setConfigs((cs) => (cs.length ? cs.map((c) => ({ ...c, kb_id: id })) : id ? [{ ...DEFAULT_RAG, kb_id: id, label: "Config 1" }] : []));
  }
  const setCfg = (i: number, c: RagConfig) => setConfigs((cs) => cs.map((x, j) => (j === i ? c : x)));

  const create = useMutation({
    mutationFn: () =>
      createMatrix({
        agent_id: agentId,
        prompt_version: version ? Number(version) : null,
        configs: configs.map((c, i) => ({ ...c, mode: "retrieval", kb_id: kbId, label: c.label.trim() || `Config ${i + 1}` })),
        baselines: { no_rag: noRag, full_context: fullCtx },
        scenario_ids: scenarios,
        persona_ids: personas,
        noise_profile_ids: noise,
        repeats: Number(repeats),
        confirm_over_budget: false,
      }),
    onSuccess: (m) => {
      void qc.invalidateQueries({ queryKey: ["rag-matrices"] });
      router.push(`/rag-lab/${m.id}`);
    },
    onError: (e) => {
      setMissing(missingIndexes(e));
      setServerError(ragErrorMessage(e));
    },
  });

  function submit(ev: FormEvent) {
    ev.preventDefault();
    setServerError(null);
    setMissing([]);
    const e: Record<string, string> = {};
    if (!agentId) e["mx-agent"] = "Choose a prompt agent.";
    if (!kbId) e["mx-kb"] = "Choose the knowledge base to test.";
    if (!scenarios.length) e.Scenarios = "Pick at least one scenario.";
    if (!personas.length) e.Personas = "Pick at least one persona.";
    if (!noise.length) e["Noise profiles"] = "Pick at least one noise profile.";
    const r = Number(repeats);
    if (!Number.isInteger(r) || r < 1 || r > 10) e["mx-repeats"] = "Use a whole number from 1 to 10.";
    setErrors(e);
    const first = Object.keys(e)[0];
    if (first) return void requestAnimationFrame(() => (document.getElementById(first) ?? document.querySelector<HTMLElement>(`[aria-describedby="${first.replace(/\s+/g, "-")}-err"] input`))?.focus());
    create.mutate();
  }

  return (
    <>
      <PageHeader
        title="New RAG matrix"
        eyebrow={
          <Link href="/rag-lab" className="text-accent-fg underline-offset-2 hover:underline">
            RAG lab
          </Link>
        }
        description="One to four retrieval setups on the same knowledge base, each run on the same scenarios, plus optional no-RAG and full-context baselines."
      />
      <form onSubmit={submit} noValidate aria-label="New RAG matrix" className="grid gap-6 min-[1100px]:max-w-[900px]">
        <Panel title="Agent and knowledge base" bodyClassName="grid gap-4 sm:grid-cols-3">
          <SelectField id="mx-agent" label="Prompt agent" value={agentId} error={errors["mx-agent"]} onChange={(e) => { setAgentId(e.target.value); setVersion(""); }} help="RAG tests need a prompt (text) agent.">
            <option value="">Choose an agent</option>
            {promptAgents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </SelectField>
          <SelectField id="mx-version" label="Prompt version" value={version} onChange={(e) => setVersion(e.target.value)} disabled={!agentId}>
            <option value="">Active version</option>
            {(versions.data ?? []).map((v) => (
              <option key={v.id} value={v.version}>
                v{v.version}
              </option>
            ))}
          </SelectField>
          <SelectField id="mx-kb" label="Knowledge base" value={kbId} error={errors["mx-kb"]} onChange={(e) => pickKb(e.target.value)}>
            <option value="">Choose a knowledge base</option>
            {(kbs.data ?? []).map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
                {k.local_only ? " (local only)" : ""}
              </option>
            ))}
          </SelectField>
        </Panel>

        <Panel title="Configs" aux={<span className="num">{configs.length} of 4</span>} bodyClassName="grid gap-5">
          {configs.length === 0 && <p className="text-sm text-muted">Choose a knowledge base to add the first config.</p>}
          {configs.map((c, i) => (
            <section key={i} aria-label={`Config ${i + 1}`} className="grid gap-4 rounded-sm bg-canvas p-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <TextField id={`mx-c${i}-label`} label="Label" fieldClassName="min-w-[220px] flex-1" value={c.label} placeholder={`Config ${i + 1}`} onChange={(e) => setCfg(i, { ...c, label: e.target.value })} />
                <div className="flex gap-2">
                  <Button disabled={configs.length >= 4} aria-label={`Duplicate config ${i + 1}`} onClick={() => setConfigs((cs) => [...cs.slice(0, i + 1), { ...c, label: c.label ? `${c.label} copy` : "" }, ...cs.slice(i + 1)])}>
                    <Copy size={14} strokeWidth={1.6} aria-hidden />
                    Duplicate
                  </Button>
                  <Button variant="ghost" icon aria-label={`Remove config ${i + 1}`} disabled={configs.length <= 1} onClick={() => setConfigs((cs) => cs.filter((_, j) => j !== i))}>
                    <Trash2 size={14} strokeWidth={1.6} aria-hidden />
                  </Button>
                </div>
              </div>
              <RagConfigFields ids={`mx-c${i}`} value={c} onChange={(n) => setCfg(i, n)} kbs={kbList} showMode={false} hideKb />
            </section>
          ))}
          {configs.length > 0 && configs.length < 4 && (
            <div>
              <Button onClick={() => setConfigs((cs) => [...cs, { ...DEFAULT_RAG, kb_id: kbId, label: "" }])}>
                <Plus size={14} strokeWidth={1.6} aria-hidden />
                Add config
              </Button>
            </div>
          )}
          <div className="grid gap-3 border-t border-border pt-4 sm:grid-cols-2">
            <Switch label="No-RAG baseline" checked={noRag} onChange={setNoRag} help="The same prompt with no knowledge base. Shows what retrieval adds." />
            <Switch label="Full-context baseline" checked={fullCtx} onChange={setFullCtx} help="The whole knowledge base in the prompt. Marked n/a if it exceeds the limit." />
          </div>
        </Panel>

        <Panel title="Scenarios, personas and noise" bodyClassName="grid gap-5 sm:grid-cols-3">
          <CheckList legend="Scenarios" items={(scen.data ?? []).map((s) => ({ id: s.id, label: s.title }))} picked={scenarios} onChange={setScenarios} error={errors.Scenarios} empty={<>No scenarios tagged <code className="mono">rag</code> yet. Generate or import questions from a knowledge base, or tag scenarios yourself.</>} />
          <CheckList legend="Personas" items={(pers.data ?? []).map((p) => ({ id: p.id, label: p.name }))} picked={personas} onChange={setPersonas} error={errors.Personas} empty="No personas." />
          <CheckList legend="Noise profiles" items={(noi.data ?? []).map((n) => ({ id: n.id, label: n.name }))} picked={noise} onChange={setNoise} error={errors["Noise profiles"]} empty="No noise profiles." />
          <NumberField id="mx-repeats" label="Repeats" min={1} max={10} value={repeats} onChange={(e) => setRepeats(e.target.value)} error={errors["mx-repeats"]} fieldClassName="sm:col-span-3 max-w-[160px]" help="Each scenario, persona and noise combination runs this many times." />
        </Panel>

        {serverError && (
          <Strip tone="error">
            <p>Could not create the matrix. {serverError}</p>
            {missing.length > 0 && (
              <ul aria-label="Missing indexes" className="mt-3 grid gap-2">
                {missing.map((m) => (
                  <MissingRow key={m.label} kbId={kbId} m={m} />
                ))}
              </ul>
            )}
          </Strip>
        )}
        <div>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Run matrix
          </Button>
        </div>
      </form>
    </>
  );
}
