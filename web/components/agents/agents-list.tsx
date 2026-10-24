"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, CircleX, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { LANGUAGES, relativeTime } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { LinkButton, Button } from "@/components/ui/button";
import { DataTable, FilterBar, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { FilterSelect, Switch } from "@/components/ui/field";
import { RowMenu } from "@/components/ui/row-menu";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";

type Agent = components["schemas"]["AgentOut"];
type ConnResult = components["schemas"]["TestConnectionResult"];

const AGENT_SORT: Sorters<Agent> = {
  name: (a) => a.name.toLowerCase(),
  adapter: (a) => a.adapter,
};

export function AgentsListSkeleton() {
  return (
    <>
      <PageHeader eyebrow="" title="Agents" actions={<LinkButton variant="primary" href="/agents/new">Add agent</LinkButton>} />
      <Panel bodyClassName="p-0">
        <TableSkeleton rows={5} />
      </Panel>
    </>
  );
}

/** Last run for one agent: GET /runs?agent_id=&limit=1. Shows a dash when the runs endpoint has nothing or is not available. */
function LastRun({ agentId }: { agentId: string }) {
  const q = useQuery({
    queryKey: ["agent-last-run", agentId],
    queryFn: () => call(api.GET("/api/v1/runs", { params: { query: { agent_id: agentId, limit: 1 } } })),
    retry: false,
  });
  const run = q.data?.items[0];
  if (q.isPending) return <span className="skeleton inline-block h-3 w-16 align-middle" aria-hidden />;
  if (!run) return <span className="text-subtle" title="No runs yet">-</span>;
  return (
    <Link href={`/runs/${run.id}`} className="text-accent-fg underline-offset-2 hover:underline">
      <time dateTime={run.created_at} title={run.created_at}>
        {relativeTime(run.created_at)}
      </time>
    </Link>
  );
}

function Connection({ result, testing }: { result?: ConnResult; testing: boolean }) {
  if (testing) return <span className="inline-flex items-center gap-1 text-muted"><span className="spinner" aria-hidden />Testing</span>;
  if (!result) return <span className="text-subtle" title="Not tested in this session">never tested</span>;
  if (result.ok)
    return (
      <span className="inline-flex items-center gap-1 text-pass-fg">
        <Check size={14} strokeWidth={1.6} aria-hidden />
        ok <span className="mono">{result.first_audio_ms ?? "-"} ms</span>
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-fail-fg" title={result.detail ?? undefined}>
      <CircleX size={14} strokeWidth={1.6} aria-hidden />
      <span className="mono">{result.error ?? "failed"}</span>
    </span>
  );
}

export function AgentsList() {
  const url = useUrlState();
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();

  const showArchived = url.get("archived") === "1";
  const adapter = url.get("adapter");
  const language = url.get("lang");
  const search = url.get("q");
  const sortRaw = url.get("sort");
  const sort = useMemo(() => parseSort(sortRaw), [sortRaw]);

  const list = usePagedList<Agent>(["agents", { showArchived }], (cursor) =>
    call(api.GET("/api/v1/agents", { params: { query: { include_archived: showArchived, limit: 50, cursor } } })),
  );

  const [conn, setConn] = useState<Record<string, ConnResult>>({});
  const [testing, setTesting] = useState<Set<string>>(new Set());
  const [toArchive, setToArchive] = useState<Agent | null>(null);

  const testConn = useMutation({
    mutationFn: (a: Agent) => call(api.POST("/api/v1/agents/{agent_id}/test-connection", { params: { path: { agent_id: a.id } } })),
    onMutate: (a) => setTesting((s) => new Set(s).add(a.id)),
    onSuccess: (res, a) => {
      setConn((c) => ({ ...c, [a.id]: res }));
      toast(res.ok ? `${a.name}: connected, first audio in ${res.first_audio_ms} ms.` : `${a.name}: connection failed (${res.error ?? "unknown"}).`, { tone: res.ok ? "info" : "error" });
    },
    onError: (e, a) => toast(`Could not test ${a.name}: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => testConn.mutate(a) } }),
    onSettled: (_r, _e, a) =>
      setTesting((s) => {
        const n = new Set(s);
        n.delete(a.id);
        return n;
      }),
  });

  const archive = useMutation({
    mutationFn: (a: Agent) => call(api.POST("/api/v1/agents/{agent_id}/archive", { params: { path: { agent_id: a.id } } })),
    onSuccess: (_r, a) => {
      toast(`Archived ${a.name}.`);
      setToArchive(null);
      void qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (e, a) => {
      setToArchive(null);
      toast(`Could not archive ${a.name}: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => archive.mutate(a) } });
    },
  });

  const columns: Column<Agent>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      cell: (a) => (
        <span className="inline-flex items-center gap-2">
          <Link href={`/agents/${a.id}`} className="font-medium text-fg underline-offset-2 hover:underline">
            {a.name}
          </Link>
          {a.archived && <Chip>archived</Chip>}
        </span>
      ),
    },
    { key: "adapter", header: "Adapter", mono: true, sortable: true, cell: (a) => a.adapter },
    { key: "languages", header: "Languages", mono: true, hidePhone: true, cell: (a) => (a.languages?.length ? a.languages.map((l) => l.split("-")[0]).join(" ") : <span className="text-subtle">-</span>) },
    {
      key: "glass_box",
      header: "Glass-box",
      hidePhone: true,
      cell: (a) => (a.glass_box ? <span className="inline-flex items-center gap-1"><Check size={14} strokeWidth={1.6} aria-hidden />yes</span> : <span className="text-subtle" title="Not declared">-</span>),
    },
    { key: "last_run", header: "Last run", cell: (a) => <LastRun agentId={a.id} /> },
    { key: "connection", header: "Connection", cell: (a) => <Connection result={conn[a.id]} testing={testing.has(a.id)} /> },
  ];

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = list.items.filter(
      (a) => (!adapter || a.adapter === adapter) && (!language || a.languages?.includes(language)) && (!needle || a.name.toLowerCase().includes(needle)),
    );
    // Default order: most recently updated first.
    const byUpdated = [...rows].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return sortRows(byUpdated, AGENT_SORT, sort);
  }, [list.items, search, adapter, language, sort]);

  const active = list.items.filter((a) => !a.archived).length;
  const archivedCount = list.items.length - active;
  const eyebrow = list.isSuccess ? `${active} active${showArchived ? `, ${archivedCount} archived` : ""}${list.hasNextPage ? ", more to load" : ""}` : "";
  const filtering = !!(search || adapter || language);

  const chips = [
    ...(adapter ? [{ label: `Adapter: ${adapter}`, remove: () => url.set({ adapter: null }) }] : []),
    ...(language ? [{ label: `Language: ${language}`, remove: () => url.set({ lang: null }) }] : []),
  ];

  return (
    <>
      <PageHeader
        eyebrow={eyebrow}
        title="Agents"
        actions={
          <LinkButton variant="primary" href="/agents/new">
            <Plus size={16} strokeWidth={1.6} aria-hidden />
            Add agent
          </LinkButton>
        }
      />
      <Panel bodyClassName="p-0">
        <FilterBar search={search} onSearch={(v) => url.set({ q: v })} placeholder="Search agents" chips={chips} onClear={url.clear}>
          <FilterSelect label="Adapter" value={adapter} onChange={(v) => url.set({ adapter: v })} options={["audio_v1", "pipecat", "livekit", "vapi"].map((v) => ({ value: v, label: v }))} />
          <FilterSelect label="Language" value={language} onChange={(v) => url.set({ lang: v })} options={LANGUAGES.map((v) => ({ value: v, label: v }))} />
          <Switch label="Show archived" checked={showArchived} onChange={(v) => url.set({ archived: v ? "1" : null })} />
        </FilterBar>

        {list.isPending && <TableSkeleton rows={5} label="Loading agents" />}
        {list.isError && (
          <div className="p-4">
            <ErrorPanel error={list.error} what="agents" onRetry={() => void list.refetch()} />
          </div>
        )}
        {list.isSuccess && list.items.length === 0 && !filtering && (
          <EmptyState
            icon={Bot}
            title="No agents yet"
            body="An agent is the voice bot you want to test."
            action={
              <LinkButton variant="primary" href="/agents/new">
                Add agent
              </LinkButton>
            }
            secondary={
              <>
                Run <code className="mono">make demo</code> to create a mock agent with planted bugs.
              </>
            }
          />
        )}
        {list.isSuccess && list.items.length > 0 && filtered.length === 0 && (
          <EmptyState icon={Bot} title="No agents match these filters" body="Change or clear the filters to see more." action={<Button onClick={url.clear}>Clear filters</Button>} />
        )}
        {list.isSuccess && filtered.length > 0 && (
          <>
            <DataTable
              caption="Agents"
              columns={columns}
              rows={filtered}
              rowKey={(a) => a.id}
              sort={sort}
              onSort={(s) => url.set({ sort: s })}
              actions={(a) => (
                <RowMenu
                  label={`Actions for ${a.name}`}
                  items={[
                    { label: "Edit", onSelect: () => router.push(`/agents/${a.id}`) },
                    { label: "Test connection", onSelect: () => testConn.mutate(a), disabled: a.archived },
                    { label: "Archive", onSelect: () => setToArchive(a), destructive: true, disabled: a.archived },
                  ]}
                />
              )}
            />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>

      <ConfirmDialog
        open={!!toArchive}
        onClose={() => setToArchive(null)}
        title={`Archive ${toArchive?.name ?? "agent"}?`}
        body="Archived agents disappear from run creation but keep their history."
        confirmLabel="Archive agent"
        busy={archive.isPending}
        onConfirm={() => toArchive && archive.mutate(toArchive)}
      />
    </>
  );
}
