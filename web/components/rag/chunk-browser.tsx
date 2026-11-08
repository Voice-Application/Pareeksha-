"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { getIndex, listChunks, listDocuments } from "@/lib/api/rag";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { ErrorPanel, PageError, TableSkeleton } from "@/components/ui/states";
import { SelectField } from "@/components/ui/field";
import { IndexChip } from "./index-status";

const PAGE = 50;

export function ChunkBrowser({ kbId, indexId }: { kbId: string; indexId: string }) {
  const [doc, setDoc] = useState("");
  const index = useQuery({ queryKey: ["kb-index", kbId, indexId], queryFn: () => getIndex(kbId, indexId), retry: false });
  const docs = useQuery({ queryKey: ["kb-docs", kbId], queryFn: () => listDocuments(kbId), select: (p) => p.items ?? [] });
  const names = useMemo(() => new Map((docs.data ?? []).map((d) => [d.id, d.filename])), [docs.data]);
  const chunks = useInfiniteQuery({
    queryKey: ["kb-chunks", kbId, indexId, doc],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => listChunks(kbId, indexId, pageParam, PAGE, doc),
    getNextPageParam: (last, all) => (Array.isArray(last) && last.length === PAGE ? all.length * PAGE : undefined),
  });
  const rows = (chunks.data?.pages ?? []).flatMap((p) => (Array.isArray(p) ? p : []));

  if (index.isError) return <PageError error={index.error} onRetry={() => void index.refetch()} backHref={`/knowledge-bases/${kbId}`} backLabel="Back to the knowledge base" />;
  return (
    <>
      <PageHeader
        title={index.data ? `Chunks of index v${index.data.version}` : "Chunks"}
        eyebrow={
          <>
            <Link href={`/knowledge-bases/${kbId}`} className="text-accent-fg underline-offset-2 hover:underline">
              Knowledge base
            </Link>
            {index.data && <IndexChip status={index.data.status} />}
            {index.data && <span className="num">{index.data.chunk_count.toLocaleString("en-IN")} chunks</span>}
          </>
        }
        description="The text the retriever searches. Check where chunk boundaries fall in your documents."
      />
      <Panel
        title="Chunks"
        bodyClassName="grid gap-4"
        aux={
          <SelectField id="chunk-doc" label="Document" fieldClassName="min-w-[220px]" value={doc} onChange={(e) => setDoc(e.target.value)}>
            <option value="">All documents</option>
            {(docs.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </SelectField>
        }
      >
        {chunks.isPending && <TableSkeleton rows={5} label="Loading chunks" />}
        {chunks.isError && <ErrorPanel error={chunks.error} what="chunks" onRetry={() => void chunks.refetch()} />}
        {chunks.isSuccess && rows.length === 0 && <p className="text-sm text-muted">No chunks.</p>}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="rt">
              <caption className="sr-only">Chunks</caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Document</th>
                  <th scope="col">Characters</th>
                  <th scope="col">Text</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td className="num" data-label="">
                      {c.ordinal}
                    </td>
                    <td data-label="Document" className="mono break-all text-xs">
                      {names.get(c.document_id) ?? c.document_id.slice(0, 8)}
                    </td>
                    <td data-label="Characters" className="num whitespace-nowrap text-xs text-muted">
                      {c.start_char}–{c.end_char}
                    </td>
                    <td data-label="Text">
                      <details>
                        <summary className="cursor-pointer list-none">
                          <span className="line-clamp-2 whitespace-pre-wrap">{c.text}</span>
                          <span className="text-xs text-accent-fg">Show full chunk</span>
                        </summary>
                        <p className="mt-2 whitespace-pre-wrap rounded-sm bg-sunken p-3 text-sm">{c.text}</p>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {chunks.hasNextPage && (
          <div>
            <Button loading={chunks.isFetchingNextPage} onClick={() => void chunks.fetchNextPage()}>
              Load more
            </Button>
          </div>
        )}
      </Panel>
    </>
  );
}
