"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleX, Play } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { Run } from "@/lib/api/runs";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { DataTable, FilterBar, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { RowMenu } from "@/components/ui/row-menu";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { Meter, ProgressBar, StatusPill, VerdictBadge } from "@/components/ui/measure";

const SORT: Sorters<Run> = {
  name: (r) => r.name.toLowerCase(),
  status: (r) => r.status,
  calls: (r) => r.progress.total,
  pass_rate: (r) => r.summary?.pass_rate ?? null,
  critical: (r) => r.summary?.critical_failures ?? null,
  mean: (r) => r.summary?.score_mean ?? null,
  created: (r) => r.created_at,
};

const IN_FLIGHT = new Set(["queued", "running", "draft"]);

export function RunsListSkeleton() {
  return (
    <>
      <PageHeader title="Runs" actions={<LinkButton variant="primary" href="/runs/new">New run</LinkButton>} />
      <Panel bodyClassName="p-0">
        <TableSkeleton rows={8} />
      </Panel>
    </>
  );
}

export function PassRateCell({ run }: { run: Run }) {
  if (run.kind === "regression" && run.summary?.suite_passed !== undefined && run.summary.suite_passed !== null)
    return <VerdictBadge verdict={run.summary.suite_passed ? "pass" : "fail"} />;
  if (IN_FLIGHT.has(run.status) || run.status === "failed")
    return run.status === "failed" ? (
      <span className="text-subtle" title="The run failed before it produced results">-</span>
    ) : (
      <span className="block w-32">
        <ProgressBar done={run.progress.evaluated + run.progress.error} total={run.progress.total} label="Run progress" />
      </span>
    );
  const pr = run.summary?.pass_rate;
  if (pr === null || pr === undefined) return <span className="text-subtle" title="No evaluated calls yet">-</span>;
  const pct = Math.round(pr * 100);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="mono w-9 text-right">{pct}%</span>
      <Meter value={pct} passLine={null} label={`Pass rate ${pct}%`} />
    </span>
  );
}

export function RunsList() {
  const url = useUrlState();
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const agent = url.get("agent");
  const kind = url.get("kind");
  const status = url.get("status");
  const search = url.get("q");
  const sortRaw = url.get("sort");
  const sort = useMemo(() => parseSort(sortRaw), [sortRaw]);
  const [picked, setPicked] = useState<string[]>([]);
  const [toCancel, setToCancel] = useState<Run | null>(null);

  const agents = useQuery({ queryKey: ["agents", "options"], queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 100 } } })) });
  const list = usePagedList<Run>(["runs", { agent, kind, status }], (cursor) =>
    call(
      api.GET("/api/v1/runs", {
        params: { query: { agent_id: agent || undefined, kind: (kind || undefined) as Run["kind"] | undefined, status: (status || undefined) as Run["status"] | undefined, limit: 50, cursor } },
      }),
    ),
  );
  const anyActive = list.items.some((r) => IN_FLIGHT.has(r.status));
  // Running rows update through a 5 s poll (06-runs).
  useQuery({
    queryKey: ["runs-poll", { agent, kind, status }],
    queryFn: async () => {
      await list.refetch();
      return null;
    },
    enabled: anyActive,
    refetchInterval: 5000,
  });

  const agentName = (id: string) => agents.data?.items?.find((a) => a.id === id)?.name ?? id.slice(0, 8);

  const cancel = useMutation({
    mutationFn: (r: Run) => call(api.POST("/api/v1/runs/{run_id}/cancel", { params: { path: { run_id: r.id } } })),
    onSuccess: (_d, r) => {
      toast(`Cancelling ${r.name || "run"}.`);
      setToCancel(null);
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (e, r) => {
      setToCancel(null);
      if (e instanceof ApiError && e.status === 409) {
        toast("That run already finished.", { tone: "info" });
        void qc.invalidateQueries({ queryKey: ["runs"] });
        return;
      }
      toast(`Could not cancel: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => cancel.mutate(r) } });
    },
  });

  const needle = search.trim().toLowerCase();
  const rows = useMemo(() => {
    const filtered = needle ? list.items.filter((r) => (r.name || "").toLowerCase().includes(needle) || r.id.startsWith(needle)) : list.items;
    return sortRows(filtered, SORT, sort ?? { key: "created", dir: "desc" });
  }, [list.items, needle, sort]);

  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= 2 ? [p[1], id] : [...p, id]));
  const byId = (id: string) => list.items.find((r) => r.id === id);
  const compareHref = () => {
    const [a, b] = picked.map(byId);
    if (!a || !b) return "/runs/compare";
    const [base, head] = a.created_at <= b.created_at ? [a, b] : [b, a];
    return `/runs/compare?base=${base.id}&head=${head.id}`;
  };

  const columns: Column<Run>[] = [
    {
      key: "select",
      header: "Select",
      cell: (r) => (
        <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" aria-label={`Select ${r.name || r.id.slice(0, 8)} for compare`} checked={picked.includes(r.id)} onChange={() => toggle(r.id)} />
      ),
    },
    {
      key: "name",
      header: "Name",
      sortable: true,
      cell: (r) => (
        <Link href={`/runs/${r.id}`} className="font-medium text-fg underline-offset-2 hover:underline">
          {r.name || `Run ${r.id.slice(0, 8)}`}
        </Link>
      ),
    },
    { key: "agent", header: "Agent", hidePhone: true, cell: (r) => <span className="text-muted">{agentName(r.agent_id)}</span> },
    { key: "kind", header: "Kind", mono: true, hidePhone: true, cell: (r) => r.kind },
    { key: "status", header: "Status", sortable: true, cell: (r) => <StatusPill status={r.status} /> },
    { key: "calls", header: "Calls", mono: true, sortable: true, cell: (r) => (IN_FLIGHT.has(r.status) ? `${r.progress.evaluated + r.progress.error}/${r.progress.total}` : r.progress.total) },
    { key: "pass_rate", header: "Pass rate", sortable: true, cell: (r) => <PassRateCell run={r} /> },
    {
      key: "critical",
      header: "Crit",
      sortable: true,
      mono: true,
      hidePhone: true,
      cell: (r) => {
        const n = r.summary?.critical_failures;
        if (n === null || n === undefined) return <span className="text-subtle">-</span>;
        return n > 0 ? (
          <span className="inline-flex items-center gap-1 text-fail-fg">
            <CircleX size={14} strokeWidth={1.6} aria-hidden />
            {n}
          </span>
        ) : (
          <span className="text-muted">0</span>
        );
      },
    },
    { key: "mean", header: "Mean", mono: true, sortable: true, hidePhone: true, cell: (r) => (r.summary?.score_mean != null ? r.summary.score_mean.toFixed(1) : <span className="text-subtle">-</span>) },
    {
      key: "created",
      header: "When",
      sortable: true,
      cell: (r) => (
        <time dateTime={r.created_at} title={r.created_at} className="text-muted">
          {relativeTime(r.created_at)}
        </time>
      ),
    },
  ];

  const chips = [
    ...(agent ? [{ label: `Agent: ${agentName(agent)}`, remove: () => url.set({ agent: null }) }] : []),
    ...(kind ? [{ label: `Kind: ${kind}`, remove: () => url.set({ kind: null }) }] : []),
    ...(status ? [{ label: `Status: ${status}`, remove: () => url.set({ status: null }) }] : []),
  ];

  return (
    <>
      <PageHeader
        eyebrow={list.isSuccess ? `${list.items.length} run${list.items.length === 1 ? "" : "s"}${agent ? ` for ${agentName(agent)}` : ""}` : ""}
        title="Runs"
        actions={
          <>
            <Button disabled={picked.length !== 2} title={picked.length === 2 ? undefined : "Select two runs"} onClick={() => router.push(compareHref())}>
              Compare
            </Button>
            <LinkButton variant="primary" href="/runs/new">
              <Play size={14} strokeWidth={1.6} aria-hidden />
              New run
            </LinkButton>
          </>
        }
      />
      <Panel bodyClassName="p-0">
        <FilterBar search={search} onSearch={(v) => url.set({ q: v })} placeholder="Search runs by name" chips={chips} onClear={() => url.clear()}>
          <FilterSelect label="Agent" value={agent} onChange={(v) => url.set({ agent: v })} options={[{ value: "", label: "All agents" }, ...(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))]} />
          <FilterSelect label="Kind" value={kind} onChange={(v) => url.set({ kind: v })} options={[{ value: "", label: "All kinds" }, { value: "matrix", label: "matrix" }, { value: "regression", label: "regression" }, { value: "dry_run", label: "dry_run" }]} />
          <FilterSelect
            label="Status"
            value={status}
            onChange={(v) => url.set({ status: v })}
            options={[{ value: "", label: "All statuses" }, ...["queued", "running", "completed", "partial", "cancelled", "failed"].map((s) => ({ value: s, label: s }))]}
          />
        </FilterBar>
        {list.isPending ? (
          <TableSkeleton rows={8} label="Loading runs" />
        ) : list.isError ? (
          <div className="p-4">
            <ErrorPanel error={list.error} what="runs" onRetry={() => void list.refetch()} />
          </div>
        ) : rows.length === 0 ? (
          chips.length || needle ? (
            <EmptyState icon={Play} title="No runs match these filters" body="Try a different filter or clear them." action={<Button onClick={() => url.clear()}>Clear filters</Button>} />
          ) : (
            <EmptyState
              icon={Play}
              title="No runs yet"
              body="A run sends synthetic callers to your agent and scores every call."
              action={<LinkButton variant="primary" href="/runs/new">New run</LinkButton>}
            />
          )
        ) : (
          <>
            <DataTable
              caption="Runs"
              columns={columns}
              rows={rows}
              rowKey={(r) => r.id}
              sort={sort ?? { key: "created", dir: "desc" }}
              onSort={(n) => url.set({ sort: n })}
              actions={(r) => (
                <RowMenu
                  label={`Actions for ${r.name || r.id.slice(0, 8)}`}
                  items={[
                    { label: "Open", onSelect: () => router.push(`/runs/${r.id}`) },
                    { label: "Compare with previous", onSelect: () => router.push(`/runs/compare?head=${r.id}`) },
                    { label: "Cancel run", destructive: true, disabled: !IN_FLIGHT.has(r.status), onSelect: () => setToCancel(r) },
                    { label: "Copy id", onSelect: () => void navigator.clipboard?.writeText(r.id) },
                  ]}
                />
              )}
            />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>
      <ConfirmDialog
        open={!!toCancel}
        onClose={() => setToCancel(null)}
        title="Cancel run"
        body="In-flight calls will hang up cleanly. Cancel run?"
        confirmLabel="Cancel run"
        busy={cancel.isPending}
        onConfirm={() => toCancel && cancel.mutate(toCancel)}
      />
    </>
  );
}
