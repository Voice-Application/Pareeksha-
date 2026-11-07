"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { buildIndex, listIndexes, ragErrorMessage, type ChunkingConfig, type EmbeddingConfig } from "@/lib/api/rag";
import { Chip } from "@/components/ui/layout";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

export const isActive = (s: string) => s === "pending" || s === "building";

/** Indexes of one KB. Polls every 3 s while any is pending or building; react-query stops the timer on unmount. */
export function useIndexes(kbId: string, enabled = true) {
  return useQuery({
    queryKey: ["kb-indexes", kbId],
    queryFn: () => listIndexes(kbId),
    enabled,
    select: (p) => p.items ?? [],
    refetchInterval: (q) => ((q.state.data?.items ?? []).some((i) => isActive(i.status)) ? 3000 : false),
  });
}

export function IndexChip({ status }: { status: string }) {
  const tone = status === "ready" ? "text-pass-fg" : status === "failed" ? "text-fail-fg" : "text-warn-fg";
  return (
    <Chip className={cn("gap-1.5", tone)}>
      {isActive(status) && <span className="spinner" aria-hidden />}
      <span>{status}</span>
    </Chip>
  );
}

/** Starts an index build and says in a toast whether a new version was queued or an identical one was reused (200 vs 201). */
export function useBuildIndex(kbId: string) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (v: { chunking: ChunkingConfig; embedding: EmbeddingConfig }) => buildIndex(kbId, v),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["kb-indexes", kbId] });
      toast(r.created ? `Building index v${r.index.version}.` : `Using existing index v${r.index.version}.`);
    },
    onError: (e) => toast(ragErrorMessage(e), { tone: "error" }),
  });
}
