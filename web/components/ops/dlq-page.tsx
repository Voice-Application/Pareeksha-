"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Minus } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { ConfirmDialog, Sheet } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { CodeBlock } from "./code-block";

type DL = components["schemas"]["DeadLetterOut"];

function DlStatus({ s }: { s: DL["status"] }) {
  const Icon = s === "open" ? CircleX : s === "replayed" ? CircleCheck : Minus;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${s === "open" ? "text-fail-fg" : "text-muted"}`}>
      <Icon size={14} strokeWidth={1.6} aria-hidden />
      {s}
    </span>
  );
}

const SORT: Sorters<DL> = { failed: (d) => d.failed_at, topic: (d) => d.original_topic, group: (d) => d.consumer_group, attempts: (d) => d.attempts };

export function DlqPage() {
  const url = useUrlState();
  const qc = useQueryClient();
  const { toast } = useToast();
  const status = url.get("status", "open");
  const topic = url.get("topic");
  const group = url.get("group");
  const sort = useMemo(() => parseSort(url.get("sort")) ?? { key: "failed", dir: "desc" as const }, [url]);
  const [open, setOpen] = useState<DL | null>(null);
  const [confirm, setConfirm] = useState<"discard" | "all" | null>(null);

  const list = usePagedList<DL>(["dlq", status], (cursor) => call(api.GET("/api/v1/dlq", { params: { query: { status: (status || undefined) as DL["status"] | undefined, limit: 100, cursor } } })));
  // The list refetches every 15 s and on focus (15-dlq).
  useQuery({ queryKey: ["dlq-poll", status], queryFn: async () => { await list.refetch(); return null; }, refetchInterval: 15000, refetchOnWindowFocus: true });
  const rows = useMemo(() => sortRows(list.items.filter((d) => (!topic || d.original_topic === topic) && (!group || d.consumer_group === group)), SORT, sort), [list.items, topic, group, sort]);
  const topics = [...new Set(list.items.map((d) => d.original_topic))];
  const groups = [...new Set(list.items.map((d) => d.consumer_group))];

  const act = useMutation({
    mutationFn: ({ d, kind }: { d: DL; kind: "replay" | "discard" }) =>
      kind === "replay"
        ? call(api.POST("/api/v1/dlq/{dead_letter_id}/replay", { params: { path: { dead_letter_id: d.id } } }))
        : call(api.POST("/api/v1/dlq/{dead_letter_id}/discard", { params: { path: { dead_letter_id: d.id } } })),
    onSuccess: (_r, { kind }) => {
      toast(kind === "replay" ? "Replayed. It will be processed again with attempt 1." : "Discarded.");
      setOpen(null);
      setConfirm(null);
      void qc.invalidateQueries({ queryKey: ["dlq"] });
      void qc.invalidateQueries({ queryKey: ["metrics"] });
    },
    onError: (e) => {
      setConfirm(null);
      toast(`Could not complete: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error" });
    },
  });

  const openRows = list.items.filter((d) => d.status === "open");
  const title = status === "open" || !status ? (openRows.length === 0 && list.isSuccess ? "The dead-letter queue is empty" : `${openRows.length} event${openRows.length === 1 ? " is" : "s are"} waiting in the dead-letter queue`) : "Dead-letter queue";
  const columns: Column<DL>[] = [
    { key: "failed", header: "Failed", sortable: true, cell: (d) => <time dateTime={d.failed_at} title={d.failed_at} className="text-muted">{relativeTime(d.failed_at)}</time> },
    { key: "topic", header: "Original topic", mono: true, sortable: true, cell: (d) => <button type="button" className="underline-offset-2 hover:underline" onClick={() => setOpen(d)}>{d.original_topic}</button> },
    { key: "group", header: "Consumer", mono: true, sortable: true, cell: (d) => d.consumer_group },
    { key: "error", header: "Error", hidePhone: true, cell: (d) => <span className="mono block max-w-[420px] truncate text-xs" title={d.error}>{d.error}</span> },
    { key: "attempts", header: "Attempts", mono: true, sortable: true, cell: (d) => d.attempts },
    { key: "status", header: "Status", cell: (d) => <DlStatus s={d.status} /> },
  ];

  return (
    <>
      <PageHeader
        eyebrow={list.isSuccess ? `${openRows.length} open in this view` : ""}
        title={title}
        description="Events that failed three times land here. Replaying re-publishes the event from the start; discarding drops it."
        actions={
          <Button disabled={status !== "open" || openRows.length === 0} onClick={() => setConfirm("all")}>
            Replay all open
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <FilterSelect label="Status" value={status} onChange={(v) => url.set({ status: v || "all" })} options={[{ value: "open", label: "open" }, { value: "replayed", label: "replayed" }, { value: "discarded", label: "discarded" }, { value: "all", label: "all statuses" }]} />
          <FilterSelect label="Topic" value={topic} onChange={(v) => url.set({ topic: v })} options={[{ value: "", label: "All topics" }, ...topics.map((t) => ({ value: t, label: t }))]} />
          <FilterSelect label="Consumer" value={group} onChange={(v) => url.set({ group: v })} options={[{ value: "", label: "All consumers" }, ...groups.map((t) => ({ value: t, label: t }))]} />
        </div>
        {list.isPending ? (
          <TableSkeleton rows={4} label="Loading dead letters" />
        ) : list.isError ? (
          <div className="p-4"><ErrorPanel error={list.error} what="the dead-letter queue" onRetry={() => void list.refetch()} /></div>
        ) : rows.length === 0 ? (
          status === "open" && !topic && !group ? (
            <EmptyState icon={CircleCheck} title="The dead-letter queue is empty" body="Events that fail three times will appear here." />
          ) : (
            <EmptyState icon={CircleCheck} title="No events match these filters" body="Try another status or clear the filters." action={<Button onClick={() => url.clear()}>Clear filters</Button>} />
          )
        ) : (
          <>
            <DataTable caption="Dead-letter events" columns={columns} rows={rows} rowKey={(d) => d.id} sort={sort} onSort={(n) => url.set({ sort: n })} />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={rows.length} />
          </>
        )}
      </Panel>

      <Sheet
        open={!!open}
        onClose={() => setOpen(null)}
        title="Dead-letter event"
        wide
        footer={
          open && (
            <div className="flex flex-wrap justify-end gap-2">
              <Button onClick={() => void navigator.clipboard?.writeText(open.event_id)}>Copy event id</Button>
              <Button variant="destructive" disabled={open.status !== "open"} onClick={() => setConfirm("discard")}>Discard</Button>
              <Button variant="primary" disabled={open.status !== "open"} loading={act.isPending && act.variables?.kind === "replay"} onClick={() => act.mutate({ d: open, kind: "replay" })}>Replay</Button>
            </div>
          )
        }
      >
        {open && (
          <div className="flex flex-col gap-4">
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="eyebrow">Topic</dt><dd className="mono break-all">{open.original_topic}</dd></div>
              <div><dt className="eyebrow">Consumer</dt><dd className="mono">{open.consumer_group}</dd></div>
              <div><dt className="eyebrow">Attempts</dt><dd className="mono">{open.attempts}</dd></div>
              <div><dt className="eyebrow">Status</dt><dd><DlStatus s={open.status} /></dd></div>
            </dl>
            <div><p className="eyebrow mb-1">Error</p><CodeBlock label="error" text={open.error} /></div>
            <div><p className="eyebrow mb-1">Envelope (as received, PII masked)</p><CodeBlock label="envelope JSON" text={JSON.stringify(open.envelope, null, 2)} /></div>
          </div>
        )}
      </Sheet>
      <ConfirmDialog
        open={confirm === "discard"}
        onClose={() => setConfirm(null)}
        title="Discard event"
        body="Discard permanently? The event will not be processed."
        confirmLabel="Discard"
        busy={act.isPending}
        onConfirm={() => open && act.mutate({ d: open, kind: "discard" })}
      />
      <ConfirmDialog
        open={confirm === "all"}
        onClose={() => setConfirm(null)}
        title="Replay all open events"
        body={`Replay ${openRows.length} open event${openRows.length === 1 ? "" : "s"} (${[...new Set(openRows.map((d) => d.original_topic))].join(", ")})? They are processed one at a time.`}
        confirmLabel="Replay all"
        onConfirm={async () => {
          for (const d of openRows) {
            try {
              await call(api.POST("/api/v1/dlq/{dead_letter_id}/replay", { params: { path: { dead_letter_id: d.id } } }));
            } catch (e) {
              toast(`Stopped at ${d.event_id.slice(0, 8)}: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error" });
              break;
            }
          }
          setConfirm(null);
          void qc.invalidateQueries({ queryKey: ["dlq"] });
        }}
      />
    </>
  );
}
