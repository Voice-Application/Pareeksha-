"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Plus, Sparkles } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { useAgentOptions } from "@/lib/hooks/use-agents";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { DataTable, FilterBar, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { RowMenu } from "@/components/ui/row-menu";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { GenerateSheet } from "./generate-sheet";

type Scenario = components["schemas"]["ScenarioOut"];

export const TAG_SUGGESTIONS = ["happy_path", "edge_case", "adversarial", "payment_dispute"];

export function ScenariosListSkeleton() {
  return (
    <>
      <PageHeader eyebrow="" title="Scenarios" actions={<LinkButton variant="primary" href="/scenarios/new">New scenario</LinkButton>} />
      <Panel bodyClassName="p-0">
        <TableSkeleton rows={6} />
      </Panel>
    </>
  );
}

const SCENARIO_SORT: Sorters<Scenario> = {
  title: (s) => s.title.toLowerCase(),
  source: (s) => s.source,
  max_turns: (s) => s.max_turns,
};

function toCreateBody(s: Scenario): components["schemas"]["ScenarioCreate"] {
  return {
    agent_id: s.agent_id,
    title: `${s.title} (copy)`,
    caller_goal: s.caller_goal,
    fixtures: s.fixtures,
    reveal_rules: s.reveal_rules,
    success_criteria: s.success_criteria,
    must_say: s.must_say,
    must_not_say: s.must_not_say,
    expected_tool_calls: s.expected_tool_calls,
    caller_speaks_first: s.caller_speaks_first,
    max_turns: s.max_turns,
    tags: s.tags,
  };
}

export function ScenariosList() {
  const url = useUrlState();
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const agents = useAgentOptions();

  const agentId = url.get("agent");
  const tag = url.get("tag");
  const source = url.get("source");
  const search = url.get("q");
  const sortRaw = url.get("sort");
  const sort = useMemo(() => parseSort(sortRaw), [sortRaw]);

  const list = usePagedList<Scenario>(["scenarios", { agentId, tag }], (cursor) =>
    call(api.GET("/api/v1/scenarios", { params: { query: { agent_id: agentId || null, tag: tag || null, limit: 50, cursor } } })),
  );

  const [toDelete, setToDelete] = useState<Scenario | null>(null);
  const [refused, setRefused] = useState<{ scenario: Scenario; message: string; runs: { id: string; name?: string }[] } | null>(null);
  const [generateOpen, setGenerateOpen] = useState(false);

  const duplicate = useMutation({
    mutationFn: (s: Scenario) => call(api.POST("/api/v1/scenarios", { body: toCreateBody(s) })),
    onSuccess: (created) => {
      toast(`Created ${created.title}.`);
      void qc.invalidateQueries({ queryKey: ["scenarios"] });
    },
    onError: (e, s) => toast(`Could not duplicate: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => duplicate.mutate(s) } }),
  });

  const del = useMutation({
    mutationFn: (s: Scenario) => call(api.DELETE("/api/v1/scenarios/{scenario_id}", { params: { path: { scenario_id: s.id } } })),
    onSuccess: (_r, s) => {
      setToDelete(null);
      toast(`Deleted ${s.title}.`);
      void qc.invalidateQueries({ queryKey: ["scenarios"] });
    },
    onError: (e, s) => {
      setToDelete(null);
      if (e instanceof ApiError && e.status === 409) {
        const runs = Array.isArray(e.details.runs) ? (e.details.runs as { id: string; name?: string }[]) : [];
        setRefused({ scenario: s, message: e.userMessage(), runs });
      } else toast(`Could not delete: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => del.mutate(s) } });
    },
  });

  const agentName = (id?: string | null) => agents.data?.find((a) => a.id === id)?.name;

  const columns: Column<Scenario>[] = [
    {
      key: "title",
      header: "Title",
      sortable: true,
      cell: (s) => (
        <Link href={`/scenarios/${s.id}`} className="font-medium text-fg underline-offset-2 hover:underline">
          {s.title}
        </Link>
      ),
    },
    {
      key: "source",
      header: "Source",
      sortable: true,
      cell: (s) =>
        s.source === "promoted" && s.source_call_id ? (
          <span className="inline-flex items-center gap-2">
            <Chip>promoted</Chip>
            <Link href={`/calls/${s.source_call_id}`} className="mono text-xs text-accent-fg underline-offset-2 hover:underline">
              call {s.source_call_id.slice(0, 8)}
            </Link>
          </span>
        ) : (
          <Chip>{s.source}</Chip>
        ),
    },
    {
      key: "tags",
      header: "Tags",
      hidePhone: true,
      cell: (s) =>
        s.tags?.length ? (
          <span className="flex flex-wrap gap-1">
            {s.tags.slice(0, 3).map((t) => (
              <Chip key={t} mono>
                {t}
              </Chip>
            ))}
            {s.tags.length > 3 && <span className="text-xs text-subtle">+{s.tags.length - 3}</span>}
          </span>
        ) : (
          <span className="text-subtle">-</span>
        ),
    },
    { key: "max_turns", header: "Max turns", mono: true, sortable: true, cell: (s) => s.max_turns },
    { key: "used_in", header: "Used in", hidePhone: true, cell: () => <span className="text-subtle" title="Not available: the API does not report usage yet">-</span> },
  ];

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = list.items.filter((s) => (!source || s.source === source) && (!needle || s.title.toLowerCase().includes(needle) || s.caller_goal.toLowerCase().includes(needle)));
    return sortRows([...rows].sort((a, b) => b.updated_at.localeCompare(a.updated_at)), SCENARIO_SORT, sort);
  }, [list.items, search, source, sort]);

  const tagOptions = useMemo(() => [...new Set([...TAG_SUGGESTIONS, ...list.items.flatMap((s) => s.tags ?? [])])].sort(), [list.items]);
  const filtering = !!(search || agentId || tag || source);
  const eyebrow = list.isSuccess ? `${list.items.length}${list.hasNextPage ? "+" : ""} ${list.items.length === 1 ? "scenario" : "scenarios"}${agentId && agentName(agentId) ? ` for ${agentName(agentId)}` : ""}` : "";

  const chips = [
    ...(agentId ? [{ label: `Agent: ${agentName(agentId) ?? agentId.slice(0, 8)}`, remove: () => url.set({ agent: null }) }] : []),
    ...(source ? [{ label: `Source: ${source}`, remove: () => url.set({ source: null }) }] : []),
    ...(tag ? [{ label: `Tag: ${tag}`, remove: () => url.set({ tag: null }) }] : []),
  ];

  return (
    <>
      <PageHeader
        eyebrow={eyebrow}
        title="Scenarios"
        actions={
          <>
            <Button onClick={() => setGenerateOpen(true)}>
              <Sparkles size={14} strokeWidth={1.6} aria-hidden />
              Generate with AI
            </Button>
            <LinkButton variant="primary" href="/scenarios/new">
              <Plus size={16} strokeWidth={1.6} aria-hidden />
              New scenario
            </LinkButton>
          </>
        }
      />
      <Panel bodyClassName="p-0">
        <FilterBar search={search} onSearch={(v) => url.set({ q: v })} placeholder="Search scenarios" chips={chips} onClear={url.clear}>
          <FilterSelect label="Agent" value={agentId} onChange={(v) => url.set({ agent: v })} options={(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))} />
          <FilterSelect label="Source" value={source} onChange={(v) => url.set({ source: v })} options={["manual", "generated", "promoted"].map((v) => ({ value: v, label: v }))} />
          <FilterSelect label="Tag" value={tag} onChange={(v) => url.set({ tag: v })} options={tagOptions.map((v) => ({ value: v, label: v }))} />
        </FilterBar>

        {list.isPending && <TableSkeleton rows={6} label="Loading scenarios" />}
        {list.isError && (
          <div className="p-4">
            <ErrorPanel error={list.error} what="scenarios" onRetry={() => void list.refetch()} />
          </div>
        )}
        {list.isSuccess && list.items.length === 0 && !filtering && (
          <EmptyState
            icon={ListChecks}
            title="No scenarios yet"
            body="A scenario tells the synthetic caller what to try."
            action={
              <LinkButton variant="primary" href="/scenarios/new">
                New scenario
              </LinkButton>
            }
            secondary={
              <button type="button" className="text-accent-fg underline" onClick={() => setGenerateOpen(true)}>
                Generate with AI
              </button>
            }
          />
        )}
        {list.isSuccess && (list.items.length > 0 || filtering) && filtered.length === 0 && (
          <EmptyState icon={ListChecks} title="No scenarios match these filters" body="Change or clear the filters to see more." action={<Button onClick={url.clear}>Clear filters</Button>} />
        )}
        {list.isSuccess && filtered.length > 0 && (
          <>
            <DataTable
              caption="Scenarios"
              columns={columns}
              rows={filtered}
              rowKey={(s) => s.id}
              sort={sort}
              onSort={(s) => url.set({ sort: s })}
              actions={(s) => (
                <RowMenu
                  label={`Actions for ${s.title}`}
                  items={[
                    { label: "Edit", onSelect: () => router.push(`/scenarios/${s.id}`) },
                    { label: "Duplicate", onSelect: () => duplicate.mutate(s) },
                    { label: "Delete", onSelect: () => setToDelete(s), destructive: true },
                  ]}
                />
              )}
            />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>

      <ConfirmDialog
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        title={`Delete ${toDelete?.title ?? "scenario"}?`}
        body="This removes the scenario. Scenarios used by a run cannot be deleted."
        confirmLabel="Delete scenario"
        busy={del.isPending}
        onConfirm={() => toDelete && del.mutate(toDelete)}
      />
      <Dialog open={!!refused} onClose={() => setRefused(null)} title={`${refused?.scenario.title ?? "Scenario"} is in use`} footer={<Button onClick={() => setRefused(null)}>Close</Button>}>
        <p>{refused?.message}</p>
        {refused && refused.runs.length > 0 && (
          <ul className="mt-2 list-disc pl-5">
            {refused.runs.map((r) => (
              <li key={r.id}>
                <Link href={`/runs/${r.id}`} className="text-accent-fg underline">
                  {r.name ?? r.id.slice(0, 8)}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Dialog>
      <GenerateSheet open={generateOpen} onClose={() => setGenerateOpen(false)} defaultAgentId={agentId} />
    </>
  );
}
