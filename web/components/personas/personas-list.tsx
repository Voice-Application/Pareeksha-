"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { UserRound, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, fetchAudio } from "@/lib/api/call";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { LANGUAGES, LANGUAGE_LABEL, INTERRUPT_LABEL } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, FilterBar, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { RowMenu } from "@/components/ui/row-menu";
import { ConfirmDialog, Sheet } from "@/components/ui/overlay";
import { RowPlayButton } from "@/components/ui/audio";
import { useToast } from "@/components/ui/toast";
import { PersonaEditor, type Persona } from "./persona-editor";

export function PersonasListSkeleton() {
  return (
    <>
      <PageHeader eyebrow="" title="Personas" actions={<Button variant="primary" disabled>New persona</Button>} />
      <Panel bodyClassName="p-0">
        <TableSkeleton rows={8} />
      </Panel>
    </>
  );
}

const PERSONA_SORT: Sorters<Persona> = {
  name: (p) => p.name.toLowerCase(),
  language: (p) => p.language,
  mix: (p) => p.code_mix_style,
  emotion: (p) => p.emotion,
  speed: (p) => p.speed,
  interrupts: (p) => p.interruption_level,
  voice: (p) => p.voice_id,
};

/** 0-3 pips in neutral ink (not score colours). */
function Pips({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center gap-1" title={`${level}: ${INTERRUPT_LABEL[level]?.toLowerCase() ?? ""}`}>
      <span aria-hidden className="inline-flex gap-0.5">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-3 w-1.5 rounded-xs" style={{ background: i < level ? "var(--fg)" : "var(--border)" }} />
        ))}
      </span>
      <span className="mono">{level}</span>
      <span className="sr-only">{INTERRUPT_LABEL[level]}</span>
    </span>
  );
}

export function PersonasList() {
  const url = useUrlState();
  const { toast } = useToast();
  const language = url.get("lang");
  const mix = url.get("mix");
  const emotion = url.get("emotion");
  const interrupts = url.get("interrupts");
  const search = url.get("q");
  const edit = url.get("edit");
  const sortRaw = url.get("sort");
  const sort = useMemo(() => parseSort(sortRaw), [sortRaw]);

  const list = usePagedList<Persona>(["personas", { language }], (cursor) =>
    call(api.GET("/api/v1/personas", { params: { query: { language: language || null, limit: 100, cursor } } })),
  );

  const [dirty, setDirty] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);

  const editing = edit && edit !== "new" ? list.items.find((p) => p.id === edit) : undefined;

  const columns: Column<Persona>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      cell: (p) => (
        <span className="inline-flex items-center gap-2">
          <RowPlayButton label={`preview of ${p.name}`} load={() => fetchAudio(`/api/v1/personas/${p.id}/preview`)} cacheKey={JSON.stringify(p)} onError={(m) => toast(`Could not synthesise: ${m}`, { tone: "error" })} />
          <Link
            href={`/personas/${p.id}`}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey) return;
              e.preventDefault();
              url.set({ edit: p.id });
            }}
            className="font-medium text-fg underline-offset-2 hover:underline"
          >
            {p.name}
          </Link>
          {p.is_seed && <Chip>seed</Chip>}
        </span>
      ),
    },
    { key: "language", header: "Lang", mono: true, sortable: true, cell: (p) => p.language },
    { key: "mix", header: "Mix", sortable: true, cell: (p) => p.code_mix_style },
    { key: "emotion", header: "Emotion", sortable: true, cell: (p) => p.emotion },
    { key: "speed", header: "Speed", mono: true, hidePhone: true, sortable: true, cell: (p) => `${p.speed.toFixed(2).replace(/0$/, "")}x` },
    { key: "interrupts", header: "Interrupts", hidePhone: true, sortable: true, cell: (p) => <Pips level={p.interruption_level} /> },
    { key: "voice", header: "Voice", hidePhone: true, sortable: true, cell: (p) => p.voice_id },
  ];

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = list.items.filter(
      (p) => (!mix || p.code_mix_style === mix) && (!emotion || p.emotion === emotion) && (!interrupts || String(p.interruption_level) === interrupts) && (!needle || p.name.toLowerCase().includes(needle)),
    );
    return sortRows(rows, PERSONA_SORT, sort);
  }, [list.items, search, mix, emotion, interrupts, sort]);

  const counts = useMemo(() => {
    const by = (l: string) => list.items.filter((p) => p.language === l).length;
    return LANGUAGES.map((l) => ({ l, n: by(l) })).filter((x) => x.n > 0);
  }, [list.items]);
  const eyebrow = list.isSuccess ? `${list.items.length}${list.hasNextPage ? "+" : ""} ${list.items.length === 1 ? "persona" : "personas"}${counts.length ? `: ${counts.map((c) => `${c.n} ${LANGUAGE_LABEL[c.l]}`).join(", ")}` : ""}` : "";

  const filtering = !!(search || language || mix || emotion || interrupts);
  const chips = [
    ...(language ? [{ label: `Language: ${language}`, remove: () => url.set({ lang: null }) }] : []),
    ...(mix ? [{ label: `Code-mix: ${mix}`, remove: () => url.set({ mix: null }) }] : []),
    ...(emotion ? [{ label: `Emotion: ${emotion}`, remove: () => url.set({ emotion: null }) }] : []),
    ...(interrupts ? [{ label: `Interrupts: ${interrupts}`, remove: () => url.set({ interrupts: null }) }] : []),
  ];

  function requestClose() {
    if (dirty) setConfirmClose(true);
    else url.set({ edit: null });
  }

  return (
    <>
      <PageHeader
        eyebrow={eyebrow}
        title="Personas"
        actions={
          <Button variant="primary" onClick={() => url.set({ edit: "new" })}>
            <Plus size={16} strokeWidth={1.6} aria-hidden />
            New persona
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        <FilterBar search={search} onSearch={(v) => url.set({ q: v })} placeholder="Search personas" chips={chips} onClear={() => url.set({ lang: null, mix: null, emotion: null, interrupts: null, q: null })}>
          <FilterSelect label="Language" value={language} onChange={(v) => url.set({ lang: v })} options={LANGUAGES.map((l) => ({ value: l, label: LANGUAGE_LABEL[l] }))} />
          <FilterSelect label="Code-mix" value={mix} onChange={(v) => url.set({ mix: v })} options={["none", "light", "heavy"].map((v) => ({ value: v, label: v }))} />
          <FilterSelect label="Emotion" value={emotion} onChange={(v) => url.set({ emotion: v })} options={["neutral", "frustrated", "angry", "confused", "anxious", "polite", "rushed"].map((v) => ({ value: v, label: v }))} />
          <FilterSelect label="Interrupts" value={interrupts} onChange={(v) => url.set({ interrupts: v })} options={INTERRUPT_LABEL.map((l, i) => ({ value: String(i), label: `${i} ${l.toLowerCase()}` }))} />
        </FilterBar>

        {list.isPending && <TableSkeleton rows={8} label="Loading personas" />}
        {list.isError && (
          <div className="p-4">
            <ErrorPanel error={list.error} what="personas" onRetry={() => void list.refetch()} />
          </div>
        )}
        {list.isSuccess && list.items.length === 0 && !filtering && (
          <EmptyState
            icon={UserRound}
            title="No personas yet"
            body={
              <>
                Seed the 20 built-in personas with <code className="mono">make demo</code>, or create your own.
              </>
            }
            action={
              <Button variant="primary" onClick={() => url.set({ edit: "new" })}>
                New persona
              </Button>
            }
          />
        )}
        {list.isSuccess && (list.items.length > 0 || filtering) && filtered.length === 0 && (
          <EmptyState icon={UserRound} title="No personas match these filters" body="Change or clear the filters to see more." action={<Button onClick={() => url.set({ lang: null, mix: null, emotion: null, interrupts: null, q: null })}>Clear filters</Button>} />
        )}
        {list.isSuccess && filtered.length > 0 && (
          <>
            <DataTable
              caption="Personas"
              columns={columns}
              rows={filtered}
              rowKey={(p) => p.id}
              sort={sort}
              onSort={(s) => url.set({ sort: s })}
              actions={(p) => <RowMenu label={`Actions for ${p.name}`} items={[{ label: "Edit", onSelect: () => url.set({ edit: p.id }) }]} />}
            />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>

      <Sheet open={!!edit && (edit === "new" || !!editing || list.isSuccess)} onClose={requestClose} title={edit === "new" ? "New persona" : (editing?.name ?? "Persona")}>
        {edit === "new" && <PersonaEditor key="new" mode="sheet" others={list.items} onDirtyChange={setDirty} onClose={() => url.set({ edit: null })} onSaved={(p) => url.set({ edit: p.id })} />}
        {edit && edit !== "new" && editing && <PersonaEditor key={editing.id + editing.created_at} persona={editing} mode="sheet" others={list.items} onDirtyChange={setDirty} onClose={() => url.set({ edit: null })} />}
        {edit && edit !== "new" && !editing && list.isSuccess && <p className="text-sm text-muted">This persona is not in the loaded list. <Link className="text-accent-fg underline" href={`/personas/${edit}`}>Open its page</Link>.</p>}
      </Sheet>
      <ConfirmDialog
        open={confirmClose}
        onClose={() => setConfirmClose(false)}
        title="Discard changes?"
        body="Your changes to this persona have not been saved."
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
