"use client";

import { DEFAULT_RAG, EMBEDDING_PROVIDERS, METHODS, indexMatches, type KnowledgeBase, type RagConfig } from "@/lib/api/rag";
import { NumberField, SelectField, Switch, TextField } from "@/components/ui/field";
import { Button } from "@/components/ui/button";
import { Strip } from "@/components/ui/states";
import { useBuildIndex, useIndexes } from "./index-status";

const RERANKERS: RagConfig["reranker_provider"][] = ["local", "cohere", "jina", "voyage"];

/**
 * The RAG settings of one config: used by the prompt-version editor and by each card of the new-matrix page.
 * `ids` prefixes every control id so two cards on one page keep unique labels.
 */
export function RagConfigFields({
  value,
  onChange,
  ids,
  kbs,
  disabled,
  showMode = true,
  kbError,
  hideKb,
}: {
  value: RagConfig;
  onChange: (next: RagConfig) => void;
  ids: string;
  kbs: KnowledgeBase[];
  disabled?: boolean;
  showMode?: boolean;
  kbError?: string | null;
  hideKb?: boolean;
}) {
  const set = (p: Partial<RagConfig>) => onChange({ ...value, ...p });
  const ch = value.chunking ?? DEFAULT_RAG.chunking!;
  const em = value.embedding ?? DEFAULT_RAG.embedding!;
  const off = value.mode === "off";
  const retrieval = value.mode === "retrieval";
  const kb = kbs.find((k) => k.id === value.kb_id);
  return (
    <div className="grid gap-4">
      {showMode && (
        <SelectField
          id={`${ids}-mode`}
          label="RAG mode"
          value={value.mode}
          disabled={disabled}
          onChange={(e) => set({ mode: e.target.value as RagConfig["mode"] })}
          help="Retrieval puts the top chunks into the prompt. Full context sends the whole knowledge base. Off runs without it."
        >
          <option value="retrieval">Retrieval</option>
          <option value="full_context">Full context</option>
          <option value="off">Off</option>
        </SelectField>
      )}
      {!hideKb && (
      <SelectField id={`${ids}-kb`} label="Knowledge base" value={value.kb_id} disabled={disabled} error={kbError} onChange={(e) => set({ kb_id: e.target.value })}>
        <option value="">Choose a knowledge base</option>
        {kbs.map((k) => (
          <option key={k.id} value={k.id}>
            {k.name}
            {k.local_only ? " (local only)" : ""}
          </option>
        ))}
      </SelectField>
      )}

      {retrieval && (
        <>
          <fieldset className="grid gap-3 sm:grid-cols-4" disabled={disabled}>
            <legend className="mb-1 text-sm font-medium">Chunking</legend>
            <SelectField id={`${ids}-strategy`} label="Strategy" value={ch.strategy} onChange={(e) => set({ chunking: { ...ch, strategy: e.target.value as typeof ch.strategy } })}>
              <option value="recursive">Recursive</option>
              <option value="fixed">Fixed</option>
              <option value="sentence_window">Sentence window</option>
            </SelectField>
            <NumberField id={`${ids}-size`} label="Size (chars)" min={100} value={ch.size} onChange={(e) => set({ chunking: { ...ch, size: Number(e.target.value) || 0 } })} />
            <NumberField id={`${ids}-overlap`} label="Overlap (chars)" min={0} value={ch.overlap} onChange={(e) => set({ chunking: { ...ch, overlap: Number(e.target.value) || 0 } })} />
            {ch.strategy === "sentence_window" && (
              <NumberField id={`${ids}-window`} label="Window (sentences)" min={1} value={ch.window} onChange={(e) => set({ chunking: { ...ch, window: Number(e.target.value) || 1 } })} />
            )}
          </fieldset>

          <fieldset className="grid gap-3 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)]" disabled={disabled}>
            <legend className="mb-1 text-sm font-medium">Embedding</legend>
            <SelectField id={`${ids}-emb-provider`} label="Embedding provider" value={em.provider} onChange={(e) => set({ embedding: { ...em, provider: e.target.value as typeof em.provider } })}>
              {EMBEDDING_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </SelectField>
            <TextField id={`${ids}-emb-model`} label="Embedding model" className="mono" value={em.model} onChange={(e) => set({ embedding: { ...em, model: e.target.value } })} />
          </fieldset>

          <div className="grid gap-3 sm:grid-cols-3">
            <SelectField id={`${ids}-method`} label="Search method" value={value.method} disabled={disabled} onChange={(e) => set({ method: e.target.value as RagConfig["method"] })}>
              {METHODS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </SelectField>
            <NumberField id={`${ids}-topk`} label="Top K" min={1} max={50} value={value.top_k} disabled={disabled} onChange={(e) => set({ top_k: Number(e.target.value) || 1 })} help="Chunks put in the prompt." />
            <SelectField id={`${ids}-qt`} label="Query transform" value={value.query_transform} disabled={disabled} onChange={(e) => set({ query_transform: e.target.value as RagConfig["query_transform"] })}>
              <option value="none">None</option>
              <option value="multi_query">Multi-query</option>
              <option value="hyde">HyDE</option>
            </SelectField>
          </div>

          {value.method === "hybrid_rerank" && (
            <div className="grid gap-3 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)]">
              <SelectField id={`${ids}-rr-provider`} label="Reranker provider" value={value.reranker_provider} disabled={disabled} onChange={(e) => set({ reranker_provider: e.target.value as RagConfig["reranker_provider"] })}>
                {RERANKERS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </SelectField>
              <TextField id={`${ids}-rr-model`} label="Reranker model" className="mono" value={value.reranker_model} disabled={disabled} onChange={(e) => set({ reranker_model: e.target.value })} />
            </div>
          )}

          <Switch label="Small-to-big" checked={value.small_to_big} disabled={disabled} onChange={(v) => set({ small_to_big: v })} help="Search small chunks, then give the model the larger passage around each hit." />
        </>
      )}

      {value.mode === "full_context" && (
        <NumberField
          id={`${ids}-limit`}
          label="Context character limit"
          min={1000}
          value={value.context_char_limit}
          disabled={disabled}
          onChange={(e) => set({ context_char_limit: Number(e.target.value) || 1000 })}
          help="If the knowledge base is longer than this, the full-context run is marked n/a. It is never truncated."
        />
      )}

      {!off && kb && retrieval && <IndexReadiness kbId={kb.id} config={value} />}
    </div>
  );
}

/** Says whether a ready index matches the chunking and embedding, and offers to build it when none does. */
function IndexReadiness({ kbId, config }: { kbId: string; config: RagConfig }) {
  const indexes = useIndexes(kbId);
  const build = useBuildIndex(kbId);
  if (!indexes.data) return null;
  const matching = indexes.data.filter((i) => indexMatches(i, config));
  const ready = matching.find((i) => i.status === "ready");
  if (ready) return <p className="text-xs text-muted">Index <span className="mono">v{ready.version}</span> is ready for this chunking and embedding.</p>;
  const active = matching.find((i) => i.status === "pending" || i.status === "building");
  if (active)
    return (
      <Strip tone="warn">
        <p className="text-sm">Index v{active.version} is {active.status}. Runs can start once it is ready.</p>
      </Strip>
    );
  return (
    <Strip tone="warn">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 text-sm">No ready index matches this chunking and embedding. Runs with this setup are refused until one is built.</p>
        <Button className="h-8 px-3" loading={build.isPending} onClick={() => build.mutate({ chunking: config.chunking ?? DEFAULT_RAG.chunking!, embedding: config.embedding ?? DEFAULT_RAG.embedding! })}>
          Build it
        </Button>
      </div>
    </Strip>
  );
}
