"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { DEFAULT_RAG, EMBEDDING_PROVIDERS, getKnowledgeBase, listDocuments, ragErrorMessage, uploadDocument, type ChunkingConfig, type EmbeddingConfig, type KbDocument, type KbIndex } from "@/lib/api/rag";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Chip, PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { ErrorPanel, PageError, Skeleton, TableSkeleton } from "@/components/ui/states";
import { NumberField, SelectField, TextField } from "@/components/ui/field";
import { IndexChip, useBuildIndex, useIndexes } from "./index-status";
import { KbQuestions } from "./kb-questions";

type FileResult = { name: string; tone: "ok" | "info" | "error"; text: string };

function Documents({ kbId }: { kbId: string }) {
  const qc = useQueryClient();
  const docs = useQuery({ queryKey: ["kb-docs", kbId], queryFn: () => listDocuments(kbId), select: (p) => p.items ?? [] });
  const [results, setResults] = useState<FileResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function upload(files: File[]) {
    if (!files.length) return;
    setBusy(true);
    const out: FileResult[] = [];
    for (const f of files) {
      try {
        const r = await uploadDocument(kbId, f);
        out.push(r.created ? { name: f.name, tone: "ok", text: `Uploaded, ${r.doc.char_count.toLocaleString("en-IN")} characters.` } : { name: f.name, tone: "info", text: "Already uploaded." });
      } catch (e) {
        out.push({ name: f.name, tone: "error", text: ragErrorMessage(e) });
      }
    }
    setResults(out);
    setBusy(false);
    if (input.current) input.current.value = "";
    void qc.invalidateQueries({ queryKey: ["kb-docs", kbId] });
  }

  const columns: Column<KbDocument>[] = [
    { key: "file", header: "File", cell: (d) => <span className="mono break-all">{d.filename}</span> },
    { key: "mime", header: "Type", hidePhone: true, cell: (d) => <span className="text-muted">{d.mime}</span> },
    { key: "chars", header: "Characters", mono: true, cell: (d) => d.char_count.toLocaleString("en-IN") },
    {
      key: "added",
      header: "Added",
      hidePhone: true,
      cell: (d) => (
        <time dateTime={d.created_at} title={d.created_at} className="whitespace-nowrap text-muted">
          {relativeTime(d.created_at)}
        </time>
      ),
    },
  ];

  return (
    <Panel title="Documents" bodyClassName="grid gap-4" aux={docs.isSuccess ? <span className="num">{docs.data.length}</span> : null}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void upload(Array.from(e.dataTransfer.files));
        }}
        className={cn("flex flex-wrap items-center justify-between gap-3 rounded-sm border border-dashed px-4 py-4", over ? "border-accent bg-accent-tint" : "border-border-strong bg-canvas")}
      >
        <p id="kb-drop-help" className="max-w-[52ch] text-sm text-muted">
          Drop files here: txt, md, html, csv, json, pdf or docx, up to 10 MB each.
        </p>
        <Button loading={busy} onClick={() => input.current?.click()}>
          <FileUp size={14} strokeWidth={1.6} aria-hidden />
          Choose files
        </Button>
        <input ref={input} type="file" multiple className="sr-only" tabIndex={-1} aria-label="Documents to upload" aria-describedby="kb-drop-help" onChange={(e) => void upload(Array.from(e.target.files ?? []))} />
      </div>
      {results.length > 0 && (
        <ul aria-label="Upload results" className="grid gap-1 text-sm">
          {results.map((r, i) => (
            <li key={i} role={r.tone === "error" ? "alert" : "status"} className={cn("flex flex-wrap gap-x-2", r.tone === "error" && "text-fail-fg")}>
              <span className="mono break-all font-medium">{r.name}</span>
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
      )}
      {docs.isPending && <TableSkeleton rows={3} label="Loading documents" />}
      {docs.isError && <ErrorPanel error={docs.error} what="documents" onRetry={() => void docs.refetch()} />}
      {docs.isSuccess && docs.data.length === 0 && <p className="text-sm text-muted">No documents yet.</p>}
      {docs.isSuccess && docs.data.length > 0 && <DataTable caption="Documents" columns={columns} rows={docs.data} rowKey={(d) => d.id} sort={null} onSort={() => undefined} />}
    </Panel>
  );
}

function Indexes({ kbId, hasDocs }: { kbId: string; hasDocs: boolean }) {
  const indexes = useIndexes(kbId);
  const build = useBuildIndex(kbId);
  const [ch, setCh] = useState<ChunkingConfig>(DEFAULT_RAG.chunking!);
  const [em, setEm] = useState<EmbeddingConfig>(DEFAULT_RAG.embedding!);

  const columns: Column<KbIndex>[] = [
    {
      key: "v",
      header: "Index",
      cell: (i) =>
        i.status === "ready" ? (
          <Link href={`/knowledge-bases/${kbId}/indexes/${i.id}`} className="mono font-medium text-accent-fg underline-offset-2 hover:underline">
            v{i.version}
          </Link>
        ) : (
          <span className="mono font-medium">v{i.version}</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      cell: (i) => (
        <span className="flex flex-col gap-1">
          <IndexChip status={i.status} />
          {i.error && <span className="text-xs text-fail-fg">{i.error}</span>}
        </span>
      ),
    },
    {
      key: "chunking",
      header: "Chunking",
      hidePhone: true,
      cell: (i) => {
        const c = i.chunking as Partial<ChunkingConfig>;
        return (
          <span className="mono text-xs">
            {c.strategy} {c.size}/{c.overlap}
          </span>
        );
      },
    },
    {
      key: "emb",
      header: "Embedding",
      hidePhone: true,
      cell: (i) => {
        const e = i.embedding as Partial<EmbeddingConfig>;
        return (
          <span className="mono break-all text-xs">
            {e.provider} / {e.model}
          </span>
        );
      },
    },
    { key: "chunks", header: "Chunks", mono: true, cell: (i) => i.chunk_count.toLocaleString("en-IN") },
  ];

  return (
    <Panel title="Indexes" bodyClassName="grid gap-5" aux={indexes.isSuccess ? <span className="num">{indexes.data.length}</span> : null}>
      <form
        aria-label="Build index"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          build.mutate({ chunking: ch, embedding: em });
        }}
        className="grid gap-4"
      >
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-1 text-sm font-medium">Chunking</legend>
          <SelectField id="ix-strategy" label="Strategy" value={ch.strategy} onChange={(e) => setCh({ ...ch, strategy: e.target.value as ChunkingConfig["strategy"] })}>
            <option value="recursive">Recursive</option>
            <option value="fixed">Fixed</option>
            <option value="sentence_window">Sentence window</option>
          </SelectField>
          <NumberField id="ix-size" label="Size (chars)" min={100} value={ch.size} onChange={(e) => setCh({ ...ch, size: Number(e.target.value) || 0 })} />
          <NumberField id="ix-overlap" label="Overlap (chars)" min={0} value={ch.overlap} onChange={(e) => setCh({ ...ch, overlap: Number(e.target.value) || 0 })} />
        </fieldset>
        <fieldset className="grid gap-3 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)]">
          <legend className="mb-1 text-sm font-medium">Embedding</legend>
          <SelectField id="ix-provider" label="Provider" value={em.provider} onChange={(e) => setEm({ ...em, provider: e.target.value as EmbeddingConfig["provider"] })}>
            {EMBEDDING_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </SelectField>
          <TextField id="ix-model" label="Model" className="mono" value={em.model} onChange={(e) => setEm({ ...em, model: e.target.value })} help="The default is local and multilingual, so it covers Hindi and Kannada." />
        </fieldset>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" loading={build.isPending} disabled={!hasDocs}>
            Build index
          </Button>
          {!hasDocs && <span className="text-xs text-subtle">Upload a document first.</span>}
        </div>
      </form>

      {indexes.isPending && <TableSkeleton rows={2} label="Loading indexes" />}
      {indexes.isError && <ErrorPanel error={indexes.error} what="indexes" onRetry={() => void indexes.refetch()} />}
      {indexes.isSuccess && indexes.data.length === 0 && <p className="text-sm text-muted">No indexes yet. Retrieval needs a ready index.</p>}
      {indexes.isSuccess && indexes.data.length > 0 && <DataTable caption="Indexes" columns={columns} rows={indexes.data} rowKey={(i) => i.id} sort={null} onSort={() => undefined} />}
    </Panel>
  );
}

export function KbDetail({ id }: { id: string }) {
  const kb = useQuery({ queryKey: ["knowledge-base", id], queryFn: () => getKnowledgeBase(id), retry: false });
  const docs = useQuery({ queryKey: ["kb-docs", id], queryFn: () => listDocuments(id), select: (p) => p.items ?? [] });
  if (kb.isError) return <PageError error={kb.error} onRetry={() => void kb.refetch()} backHref="/knowledge-bases" backLabel="Back to knowledge bases" />;
  if (!kb.data)
    return (
      <>
        <PageHeader title="Knowledge base" />
        <Skeleton className="h-24 w-full" />
      </>
    );
  return (
    <>
      <PageHeader
        title={kb.data.name}
        eyebrow={
          <>
            <Link href="/knowledge-bases" className="text-accent-fg underline-offset-2 hover:underline">
              Knowledge
            </Link>
            {kb.data.local_only ? <Chip>local only</Chip> : <Chip>hosted models allowed</Chip>}
            {kb.data.has_secrets && <Chip>provider keys saved</Chip>}
          </>
        }
        description={kb.data.description || undefined}
      />
      <div className="grid gap-6">
        <Documents kbId={id} />
        <Indexes kbId={id} hasDocs={(docs.data?.length ?? 0) > 0} />
        <KbQuestions kbId={id} localOnly={kb.data.local_only} />
      </div>
    </>
  );
}
