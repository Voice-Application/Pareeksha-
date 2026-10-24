"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AudioLines, Plus, TriangleAlert, Scissors } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, fetchAudio } from "@/lib/api/call";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { RowMenu } from "@/components/ui/row-menu";
import { ConfirmDialog, Sheet } from "@/components/ui/overlay";
import { RowPlayButton } from "@/components/ui/audio";
import { useToast } from "@/components/ui/toast";
import { NoiseEditor, type NoiseProfile } from "./noise-editor";

export function NoiseListSkeleton() {
  return (
    <>
      <PageHeader eyebrow="" title="Noise profiles" actions={<Button variant="primary" disabled>New profile</Button>} />
      <Panel bodyClassName="p-0">
        <TableSkeleton rows={8} />
      </Panel>
    </>
  );
}

const NOISE_SORT: Sorters<NoiseProfile> = {
  name: (p) => p.name,
  rate: (p) => p.sample_rate,
  codec: (p) => p.codec,
  background: (p) => p.background_category ?? null,
  snr: (p) => p.snr_db ?? 1000,
  loss: (p) => p.packet_loss_pct,
};

const CODEC_LABEL = { none: "none", mulaw: "mu-law", alaw: "A-law" } as const;

/** Mono value plus a 48px bar in neutral ink so harsh lines are visible at a glance. */
function SnrCell({ snr }: { snr?: number | null }) {
  if (snr === null || snr === undefined) return <span className="text-subtle" title="No background noise">-</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="mono w-10">{snr} dB</span>
      <span aria-hidden className="inline-block h-1.5 w-12 overflow-hidden rounded-xs bg-sunken">
        <span className="block h-full" style={{ width: `${Math.min(100, (snr / 30) * 100)}%`, background: "var(--fg-muted)" }} />
      </span>
    </span>
  );
}

export function NoiseList() {
  const url = useUrlState();
  const { toast } = useToast();
  const edit = url.get("edit");
  const sortRaw = url.get("sort");
  const sort = useMemo(() => parseSort(sortRaw), [sortRaw]);

  const list = usePagedList<NoiseProfile>(["noise-profiles"], (cursor) => call(api.GET("/api/v1/noise-profiles", { params: { query: { limit: 100, cursor } } })));
  const [dirty, setDirty] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const editing = edit && edit !== "new" ? list.items.find((p) => p.id === edit) : undefined;

  const columns: Column<NoiseProfile>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      cell: (p) => (
        <Link
          href={`/noise-profiles/${p.id}`}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey) return;
            e.preventDefault();
            url.set({ edit: p.id });
          }}
          className="mono font-medium text-fg underline-offset-2 hover:underline"
        >
          {p.name}
        </Link>
      ),
    },
    { key: "represents", header: "Represents", hidePhone: true, cell: (p) => p.description || <span className="text-subtle">-</span> },
    { key: "rate", header: "Rate", mono: true, sortable: true, cell: (p) => `${p.sample_rate / 1000} kHz` },
    { key: "codec", header: "Codec", sortable: true, cell: (p) => CODEC_LABEL[p.codec] },
    { key: "background", header: "Background", mono: true, hidePhone: true, sortable: true, cell: (p) => p.background_category ?? <span className="text-subtle">-</span> },
    // Cleanest first: a line with no background noise counts as the highest SNR.
    { key: "snr", header: "SNR", sortable: true, cell: (p) => <SnrCell snr={p.snr_db} /> },
    {
      key: "loss",
      header: "Loss",
      mono: true,
      hidePhone: true,
      sortable: true,
      cell: (p) => (
        <span className="inline-flex items-center gap-2">
          <span>{p.packet_loss_pct}%</span>
          {p.packet_loss_pct > 0 && (
            <Chip title="Packet loss is on">
              <TriangleAlert size={12} strokeWidth={1.6} aria-hidden />
              loss
            </Chip>
          )}
          {p.clipping && (
            <Chip title="Clipping is on">
              <Scissors size={12} strokeWidth={1.6} aria-hidden />
              clip
            </Chip>
          )}
        </span>
      ),
    },
    {
      key: "preview",
      header: "Preview",
      cell: (p) => (
        <RowPlayButton label={`preview of ${p.name}`} load={() => fetchAudio(`/api/v1/noise-profiles/${p.id}/preview`)} cacheKey={JSON.stringify(p)} onError={(m) => toast(`Could not synthesise: ${m}`, { tone: "error" })} />
      ),
    },
  ];

  // Default: SNR descending, so the list reads from clean to hostile.
  const rows = useMemo(() => sortRows(list.items, NOISE_SORT, sort ?? { key: "snr", dir: "desc" }),
    [list.items, sort]);

  function requestClose() {
    if (dirty) setConfirmClose(true);
    else url.set({ edit: null });
  }

  return (
    <>
      <PageHeader
        eyebrow={list.isSuccess ? `${list.items.length}${list.hasNextPage ? "+" : ""} ${list.items.length === 1 ? "profile" : "profiles"}` : ""}
        title="Noise profiles"
        actions={
          <Button variant="primary" onClick={() => url.set({ edit: "new" })}>
            <Plus size={16} strokeWidth={1.6} aria-hidden />
            New profile
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        {list.isPending && <TableSkeleton rows={8} label="Loading noise profiles" />}
        {list.isError && (
          <div className="p-4">
            <ErrorPanel error={list.error} what="noise profiles" onRetry={() => void list.refetch()} />
          </div>
        )}
        {list.isSuccess && list.items.length === 0 && (
          <EmptyState
            icon={AudioLines}
            title="No noise profiles"
            body={
              <>
                Seed the eight built-in lines with <code className="mono">make demo</code>, or create one.
              </>
            }
            action={
              <Button variant="primary" onClick={() => url.set({ edit: "new" })}>
                New profile
              </Button>
            }
          />
        )}
        {list.isSuccess && rows.length > 0 && (
          <>
            <DataTable caption="Noise profiles" columns={columns} rows={rows} rowKey={(p) => p.id} sort={sort ?? { key: "snr", dir: "desc" }} onSort={(s) => url.set({ sort: s ?? "snr:desc" })} actions={(p) => <RowMenu label={`Actions for ${p.name}`} items={[{ label: "Edit", onSelect: () => url.set({ edit: p.id }) }]} />} />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>

      <Sheet open={!!edit && (edit === "new" || !!editing || list.isSuccess)} onClose={requestClose} title={edit === "new" ? "New noise profile" : (editing?.name ?? "Noise profile")}>
        {edit === "new" && <NoiseEditor key="new" mode="sheet" onDirtyChange={setDirty} onClose={() => url.set({ edit: null })} onSaved={(p) => url.set({ edit: p.id })} />}
        {edit && edit !== "new" && editing && <NoiseEditor key={editing.id + editing.created_at} profile={editing} mode="sheet" onDirtyChange={setDirty} onClose={() => url.set({ edit: null })} />}
        {edit && edit !== "new" && !editing && list.isSuccess && (
          <p className="text-sm text-muted">
            This profile is not in the loaded list.{" "}
            <Link className="text-accent-fg underline" href={`/noise-profiles/${edit}`}>
              Open its page
            </Link>
            .
          </p>
        )}
      </Sheet>
      <ConfirmDialog
        open={confirmClose}
        onClose={() => setConfirmClose(false)}
        title="Discard changes?"
        body="Your changes to this noise profile have not been saved."
        confirmLabel="Discard changes"
        onConfirm={() => {
          setConfirmClose(false);
          setDirty(false);
          url.set({ edit: null });
        }}
      />
    </>
  );
}
