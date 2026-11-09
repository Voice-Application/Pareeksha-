"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type CSSProperties, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FilePlus2, FileText } from "lucide-react";
import { createKnowledgeBase, listKnowledgeBases, ragErrorMessage, type KnowledgeBase } from "@/lib/api/rag";
import { relativeTime } from "@/lib/format";
import { Chip, PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { Switch, TextAreaField, TextField } from "@/components/ui/field";

const columns: Column<KnowledgeBase>[] = [
  {
    key: "name",
    header: "Name",
    cell: (k) => (
      <span className="inline-flex min-w-0 items-center gap-2">
        <FileText size={16} strokeWidth={1.6} className="shrink-0 text-subtle" aria-hidden />
        <Link href={`/knowledge-bases/${k.id}`} className="truncate font-medium text-accent-fg underline-offset-2 hover:underline">
          {k.name}
        </Link>
      </span>
    ),
  },
  { key: "desc", header: "Description", hidePhone: true, cell: (k) => (k.description ? <span className="line-clamp-2 text-muted">{k.description}</span> : <span className="text-subtle">-</span>) },
  { key: "local", header: "Data", cell: (k) => (k.local_only ? <Chip>local only</Chip> : <span className="text-muted">may use hosted models</span>) },
  {
    key: "created",
    header: "Created",
    hidePhone: true,
    cell: (k) => (
      <time dateTime={k.created_at} title={k.created_at} className="whitespace-nowrap text-muted">
        {relativeTime(k.created_at)}
      </time>
    ),
  },
];

/** Knowledge bases list with an inline create form. */
export function KbList() {
  const router = useRouter();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["knowledge-bases"], queryFn: listKnowledgeBases, select: (p) => p.items ?? [] });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [localOnly, setLocalOnly] = useState(false);
  const [embKey, setEmbKey] = useState("");
  const [rrKey, setRrKey] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      createKnowledgeBase({
        name: name.trim(),
        description: description.trim(),
        local_only: localOnly,
        secrets: embKey || rrKey ? { embedding_api_key: embKey || null, reranker_api_key: rrKey || null } : null,
      }),
    onSuccess: (kb) => {
      void qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
      router.push(`/knowledge-bases/${kb.id}`);
    },
    onError: (e) => setServerError(ragErrorMessage(e)),
  });

  /** Create the knowledge base once it has a name. */
  function submit(ev: FormEvent) {
    ev.preventDefault();
    setServerError(null);
    if (!name.trim()) return setNameError("Enter a name for the knowledge base.");
    setNameError(null);
    create.mutate();
  }

  return (
    <>
      <PageHeader title="Documents" description="The files your bot answers from. Upload them here; Pareeksha indexes them, and you can pick them in Test my prompt. The RAG lab compares chunking and embedding settings." />
      <div className="stagger grid gap-6 min-[1100px]:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Knowledge bases" bodyClassName="p-0" aux={list.isSuccess ? <span className="num">{list.data.length}</span> : null}>
          {list.isPending && <TableSkeleton rows={3} label="Loading knowledge bases" />}
          {list.isError && (
            <div className="p-5">
              <ErrorPanel error={list.error} what="knowledge bases" onRetry={() => void list.refetch()} />
            </div>
          )}
          {list.isSuccess && list.data.length === 0 && <EmptyState icon={BookOpen} title="No knowledge bases yet" body="Create one here, then upload the documents your agent should answer from." />}
          {list.isSuccess && list.data.length > 0 && <DataTable caption="Knowledge bases" columns={columns} rows={list.data} rowKey={(k) => k.id} sort={null} onSort={() => undefined} />}
        </Panel>

        <form onSubmit={submit} noValidate aria-label="New knowledge base" className="min-w-0 min-[1100px]:self-start" style={{ "--i": 1 } as CSSProperties}>
          <Panel title="New knowledge base" bodyClassName="grid gap-4">
            <TextField id="kb-name" label="Name" required value={name} onChange={(e) => setName(e.target.value)} error={nameError} />
            <TextAreaField id="kb-description" label="Description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} help="Optional." />
            <Switch label="Local only" checked={localOnly} onChange={setLocalOnly} help="Documents never leave this deployment: local embeddings and reranker only, and Pareeksha's judge will not read them." />
            {!localOnly && (
              <>
                <TextField id="kb-emb-key" label="Embedding API key" type="password" autoComplete="off" value={embKey} onChange={(e) => setEmbKey(e.target.value)} help="Only for hosted embedding providers. Write-only: it is stored encrypted and never shown again." />
                <TextField id="kb-rr-key" label="Reranker API key" type="password" autoComplete="off" value={rrKey} onChange={(e) => setRrKey(e.target.value)} help="Only for a hosted reranker. Write-only." />
              </>
            )}
            {serverError && <Strip tone="error">Could not create the knowledge base. {serverError}</Strip>}
            <div>
              <Button type="submit" variant="primary" loading={create.isPending}>
                {!create.isPending && <FilePlus2 size={16} strokeWidth={1.6} aria-hidden />}
                Create knowledge base
              </Button>
            </div>
          </Panel>
        </form>
      </div>
    </>
  );
}
