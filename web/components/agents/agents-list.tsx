"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, CircleX, Plug, Plus } from "lucide-react";
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

/** Plain labels for the adapter keys in the API schema; the raw key stays visible as a muted chip and title. */
const ADAPTER_LABEL: Record<Agent["adapter"], string> = {
  audio_v1: "Audio stream (WebSocket)",
  pipecat: "Pipecat",
  livekit: "LiveKit",
  vapi: "Vapi",
  prompt: "Prompt only (no audio)",
};
const ADAPTER_KEYS = Object.keys(ADAPTER_LABEL) as Agent["adapter"][];

/** Plain label for an adapter key, falling back to the raw key for one this build does not know. */
function adapterLabel(key: string): string {
  return ADAPTER_LABEL[key as Agent["adapter"]] ?? key;
}

const AGENT_SORT: Sorters<Agent> = {
  name: (a) => a.name.toLowerCase(),
  adapter: (a) => adapterLabel(a.adapter).toLowerCase(),
};

/*
 * Last connection result per agent id. The API does not persist test-connection results on the
 * agent, so the list keeps them in localStorage (in memory when storage is blocked) and a reload
 * does not reset every row to "not tested yet".
 */
type StoredConn = { result: ConnResult; at: string };
const CONN_STORE = "pareeksha.agents.connection.v1";
const CONN_CHANGED = "pareeksha:agents-connection";
let memoryConn = "{}";

/** Raw stored JSON, or the in-memory copy when storage is blocked or empty. */
function readConnRaw(): string {
  try {
    return window.localStorage.getItem(CONN_STORE) ?? memoryConn;
  } catch {
    /* storage blocked: use the in-memory copy */
    return memoryConn;
  }
}

/** Subscribe to stored-result changes (this tab and other tabs). */
function subscribeConn(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CONN_CHANGED, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CONN_CHANGED, onChange);
  };
}

function parseConn(raw: string): Record<string, StoredConn> {
  try {
    const v: unknown = JSON.parse(raw);
    if (!v || typeof v !== "object" || Array.isArray(v)) return {};
    // Storage is writable by anything on the origin: keep only entries with the shape the list renders.
    const out: Record<string, StoredConn> = {};
    for (const [id, e] of Object.entries(v)) {
      const s = e as Partial<StoredConn> | null;
      if (s && typeof s === "object" && typeof s.at === "string" && s.result && typeof s.result === "object" && typeof s.result.ok === "boolean") out[id] = s as StoredConn;
    }
    return out;
  } catch {
    return {};
  }
}

/** Remember one agent's latest result, with the time it ran. */
function writeConn(agentId: string, result: ConnResult) {
  const next = { ...parseConn(readConnRaw()), [agentId]: { result, at: new Date().toISOString() } };
  memoryConn = JSON.stringify(next);
  try {
    window.localStorage.setItem(CONN_STORE, memoryConn);
  } catch {
    /* convenience only: the in-memory copy still applies */
  }
  window.dispatchEvent(new Event(CONN_CHANGED));
}

/** Stored connection results; the server and first paint see none. */
function useStoredConn(): Record<string, StoredConn> {
  const raw = useSyncExternalStore(subscribeConn, readConnRaw, () => "{}");
  return useMemo(() => parseConn(raw), [raw]);
}

export function AgentsListSkeleton() {
  return (
    <>
      <PageHeader eyebrow="" title="Voice agents" actions={<LinkButton variant="primary" href="/agents/new">Add agent</LinkButton>} />
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

/** Latest result from this browser, with how long ago it ran: "ok 820 ms, 5 minutes ago". */
function ConnStatus({ stored, testing }: { stored?: StoredConn; testing: boolean }) {
  if (testing) return <span className="inline-flex items-center gap-1 text-muted"><span className="spinner" aria-hidden />Testing</span>;
  if (!stored) return <span className="text-subtle" title="No connection test from this browser yet">not tested yet</span>;
  const { result, at } = stored;
  const when = (
    <span className="text-muted">
      ,{" "}
      <time dateTime={at} title={at}>
        {relativeTime(at)}
      </time>
    </span>
  );
  if (result.ok)
    return (
      <span className="inline-flex items-center gap-1 text-pass-fg">
        <Check size={14} strokeWidth={1.6} aria-hidden />
        <span>
          ok <span className="mono">{result.first_audio_ms ?? "-"} ms</span>
          {when}
        </span>
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-fail-fg" title={result.detail ?? undefined}>
      <CircleX size={14} strokeWidth={1.6} aria-hidden />
      <span>
        <span className="mono">{result.error ?? "failed"}</span>
        {when}
      </span>
    </span>
  );
}

/** Connection cell: the latest result plus an inline Test button (the row menu keeps the same action). */
function Connection({ agent, stored, testing, onTest }: { agent: Agent; stored?: StoredConn; testing: boolean; onTest: () => void }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <ConnStatus stored={stored} testing={testing} />
      {!agent.archived && (
        <Button variant="ghost" className="h-7 gap-1 px-2 text-xs" disabled={testing} onClick={onTest} aria-label={`Test connection for ${agent.name}`}>
          <Plug size={14} strokeWidth={1.6} aria-hidden />
          Test
        </Button>
      )}
    </span>
  );
}

/** Agents table with URL-backed filters (archived, adapter, language, name) and sort, per-row connection tests and archiving. */
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

  const conn = useStoredConn();
  const [testing, setTesting] = useState<Set<string>>(new Set());
  const [toArchive, setToArchive] = useState<Agent | null>(null);

  const testConn = useMutation({
    mutationFn: (a: Agent) => call(api.POST("/api/v1/agents/{agent_id}/test-connection", { params: { path: { agent_id: a.id } } })),
    onMutate: (a) => setTesting((s) => new Set(s).add(a.id)),
    onSuccess: (res, a) => {
      writeConn(a.id, res);
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
    {
      key: "adapter",
      header: "Adapter",
      sortable: true,
      cell: (a) => (
        <span className="inline-flex flex-wrap items-center gap-2" title={`Adapter key: ${a.adapter}`}>
          {adapterLabel(a.adapter)}
          <span className="mono text-xs text-subtle">{a.adapter}</span>
        </span>
      ),
    },
    { key: "languages", header: "Languages", mono: true, hidePhone: true, cell: (a) => (a.languages?.length ? a.languages.map((l) => l.split("-")[0]).join(" ") : <span className="text-subtle">-</span>) },
    {
      // glass_box: the agent sends its own transcript and tool calls over the socket, stored per turn.
      key: "glass_box",
      header: "Shares transcript",
      hidePhone: true,
      cell: (a) =>
        a.glass_box ? (
          <span className="inline-flex items-center gap-1" title="Sends its transcript and tool calls during the call">
            <Check size={14} strokeWidth={1.6} aria-hidden />
            yes
          </span>
        ) : (
          <span className="text-subtle" title="Does not send its transcript or tool calls">-</span>
        ),
    },
    { key: "last_run", header: "Last run", cell: (a) => <LastRun agentId={a.id} /> },
    { key: "connection", header: "Connection", cell: (a) => <Connection agent={a} stored={conn[a.id]} testing={testing.has(a.id)} onTest={() => testConn.mutate(a)} /> },
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
    ...(adapter ? [{ label: `Adapter: ${adapterLabel(adapter)}`, remove: () => url.set({ adapter: null }) }] : []),
    ...(language ? [{ label: `Language: ${language}`, remove: () => url.set({ lang: null }) }] : []),
  ];

  return (
    <>
      <PageHeader
        eyebrow={eyebrow}
        title="Voice agents"
        actions={
          <LinkButton variant="primary" href="/agents/new">
            <Plus size={16} strokeWidth={1.6} aria-hidden />
            Add agent
          </LinkButton>
        }
      />
      <Panel bodyClassName="p-0">
        <FilterBar search={search} onSearch={(v) => url.set({ q: v })} placeholder="Search agents" chips={chips} onClear={url.clear}>
          <FilterSelect label="Adapter" value={adapter} onChange={(v) => url.set({ adapter: v })} options={ADAPTER_KEYS.map((v) => ({ value: v, label: adapterLabel(v) }))} />
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
            body="Add the voice agent you want to test. You will need the address it listens on."
            action={
              <LinkButton variant="primary" href="/agents/new">
                Add agent
              </LinkButton>
            }
            secondary={
              // Developer hint only: people using a deployed build have no repo to run make in.
              process.env.NODE_ENV !== "production" ? (
                <>
                  Run <code className="mono">make demo</code> to create a mock agent with planted bugs.
                </>
              ) : undefined
            }
          />
        )}
        {list.isSuccess && list.items.length > 0 && filtered.length === 0 && (
          <EmptyState icon={Bot} title="No agents match these filters" body="Change or clear the filters to see more." action={<Button onClick={url.clear}>Clear filters</Button>} />
        )}
        {list.isSuccess && filtered.length > 0 && (
          <>
            <DataTable
              caption="Voice agents"
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
