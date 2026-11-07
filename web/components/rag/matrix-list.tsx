"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { listMatrices, type RagMatrix } from "@/lib/api/rag";
import { useAgentOptions } from "@/lib/hooks/use-agents";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { LinkButton } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";

export function MatrixList() {
  const q = useQuery({ queryKey: ["rag-matrices"], queryFn: listMatrices, select: (p) => p.items ?? [] });
  const agents = useAgentOptions();
  const name = (id: string) => agents.data?.find((a) => a.id === id)?.name ?? id.slice(0, 8);
  const columns: Column<RagMatrix>[] = [
    {
      key: "created",
      header: "Matrix",
      cell: (m) => (
        <Link href={`/rag-lab/${m.id}`} className="font-medium text-accent-fg underline-offset-2 hover:underline">
          <time dateTime={m.created_at} title={m.created_at}>
            {relativeTime(m.created_at)}
          </time>
        </Link>
      ),
    },
    { key: "agent", header: "Agent", cell: (m) => name(m.agent_id) },
    { key: "entries", header: "Entries", cell: (m) => <span className="text-muted">{(m.entries ?? []).map((e) => e.label).join(", ")}</span> },
    { key: "n", header: "Configs", mono: true, hidePhone: true, cell: (m) => (m.entries ?? []).length },
  ];
  return (
    <>
      <PageHeader title="RAG lab" description="Compare retrieval setups against a no-RAG and a full-context baseline on the same scenarios. Each matrix is a group of ordinary runs." actions={<LinkButton variant="primary" href="/rag-lab/new">New matrix</LinkButton>} />
      <Panel bodyClassName="p-0">
        {q.isPending && <TableSkeleton rows={3} label="Loading matrices" />}
        {q.isError && (
          <div className="p-5">
            <ErrorPanel error={q.error} what="RAG matrices" onRetry={() => void q.refetch()} />
          </div>
        )}
        {q.isSuccess && q.data.length === 0 && (
          <EmptyState icon={FlaskConical} title="No matrices yet" body="Pick an agent and one to four retrieval setups. Pareeksha runs each one and reports hit rate, hallucination, latency and cost." action={<LinkButton href="/rag-lab/new">New matrix</LinkButton>} />
        )}
        {q.isSuccess && q.data.length > 0 && <DataTable caption="RAG matrices" columns={columns} rows={q.data} rowKey={(m) => m.id} sort={null} onSort={() => undefined} />}
      </Panel>
    </>
  );
}
