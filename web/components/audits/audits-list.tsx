"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { DataTable, FilterBar, LoadMore, parseSort, sortRows, type Column, type Sorters } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { FlagChip, ScoreChip, StatusPill, TagChip, VerdictBadge, verdictOf } from "@/components/ui/measure";

type Row = Awaited<ReturnType<typeof fetchAudits>>["items"][number];
const fetchAudits = (cursor: string | null) => call(api.GET("/api/v1/calls", { params: { query: { source: ["upload", "import"], limit: 50, cursor } } }));

const SORT: Sorters<Row> = { score: (r) => r.overall_score ?? null, started: (r) => r.started_at ?? "", lang: (r) => r.language ?? "" };

/** In-flight rows: the call is still transcribing, or transcribed but not yet scored. */
function auditStatus(r: Row): string {
  if (r.status === "completed" && !r.overall_score && r.overall_score !== 0 && r.passed == null) return "evaluating";
  return r.status;
}

export function AuditsList() {
  const url = useUrlState();
  const source = url.get("source");
  const verdict = url.get("verdict");
  const flag = url.get("flag");
  const search = url.get("q");
  const sort = useMemo(() => parseSort(url.get("sort")) ?? { key: "started", dir: "desc" as const }, [url]);

  const agents = useQuery({ queryKey: ["agents", "options"], queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 100 } } })) });
  const list = usePagedList<Row>(["audits"], fetchAudits);
  const busy = list.items.some((r) => auditStatus(r) !== "completed" && auditStatus(r) !== "error");
  // Rows in progress update every 3 s (11-audits).
  useQuery({ queryKey: ["audits-poll"], queryFn: async () => { await list.refetch(); return null; }, enabled: busy, refetchInterval: 3000 });

  const agentName = (id?: string | null) => agents.data?.items?.find((a) => a.id === id)?.name ?? "-";
  const needle = search.trim().toLowerCase();
  const rows = useMemo(
    () =>
      sortRows(
        list.items.filter((r) => (!source || r.source === source) && (!verdict || verdictOf(r) === verdict) && (flag !== "review" || r.needs_human_review) && (!needle || r.id.includes(needle) || (r.language ?? "").toLowerCase().includes(needle))),
        SORT,
        sort,
      ),
    [list.items, source, verdict, flag, needle, sort],
  );

  const columns: Column<Row>[] = [
    { key: "id", header: "Recording", mono: true, cell: (r) => <Link className="font-medium underline-offset-2 hover:underline" href={`/calls/${r.id}`}>{r.id.slice(0, 8)}</Link> },
    { key: "agent", header: "Agent", hidePhone: true, cell: (r) => <span className="text-muted">{agentName(r.agent_id)}</span> },
    { key: "source", header: "Source", mono: true, hidePhone: true, cell: (r) => (r.source === "import" ? "webhook" : r.source) },
    { key: "lang", header: "Lang", mono: true, sortable: true, cell: (r) => r.language ?? "-" },
    { key: "status", header: "Status", cell: (r) => <StatusPill status={auditStatus(r)} /> },
    { key: "score", header: "Score", sortable: true, cell: (r) => <ScoreChip score={r.overall_score} /> },
    { key: "verdict", header: "Verdict", cell: (r) => <VerdictBadge verdict={verdictOf(r)} /> },
    { key: "flag", header: "Flag", hidePhone: true, cell: (r) => (r.needs_human_review ? <FlagChip iconOnly reasons={r.review_reasons} /> : <span className="text-subtle">-</span>) },
    { key: "tags", header: "Tags", hidePhone: true, cell: (r) => (r.failure_types?.length ? <span className="flex items-center gap-1"><TagChip tag={r.failure_types[0]} />{r.failure_types.length > 1 && <span className="mono text-xs text-muted" title={r.failure_types.slice(1).join(", ")}>+{r.failure_types.length - 1}</span>}</span> : <span className="text-subtle">-</span>) },
    { key: "started", header: "Uploaded", sortable: true, cell: (r) => (r.started_at ? <time dateTime={r.started_at} title={r.started_at} className="text-muted">{relativeTime(r.started_at)}</time> : "-") },
  ];
  const chips = [
    ...(source ? [{ label: `Source: ${source === "import" ? "webhook" : source}`, remove: () => url.set({ source: null }) }] : []),
    ...(verdict ? [{ label: `Verdict: ${verdict}`, remove: () => url.set({ verdict: null }) }] : []),
    ...(flag ? [{ label: "Needs review", remove: () => url.set({ flag: null }) }] : []),
  ];
  const inFlight = list.items.filter((r) => auditStatus(r) !== "completed" && auditStatus(r) !== "error").length;

  return (
    <>
      <PageHeader
        eyebrow={list.isSuccess ? `${list.items.length} audit${list.items.length === 1 ? "" : "s"}${inFlight ? `, ${inFlight} in progress` : ""}` : ""}
        title="Audits"
        description="Score real recorded calls with the same rubric as your test runs."
        actions={<LinkButton variant="primary" href="/audits/new"><Upload size={14} strokeWidth={1.6} aria-hidden />Upload recording</LinkButton>}
      />
      <Panel bodyClassName="p-0">
        <FilterBar search={search} onSearch={(v) => url.set({ q: v })} placeholder="Search audits" chips={chips} onClear={() => url.clear()}>
          <FilterSelect label="Source" value={source} onChange={(v) => url.set({ source: v })} options={[{ value: "", label: "All sources" }, { value: "upload", label: "upload" }, { value: "import", label: "webhook" }]} />
          <FilterSelect label="Verdict" value={verdict} onChange={(v) => url.set({ verdict: v })} options={[{ value: "", label: "All verdicts" }, { value: "pass", label: "Pass" }, { value: "fail", label: "Fail" }, { value: "critical", label: "Critical" }]} />
          <FilterSelect label="Flag" value={flag} onChange={(v) => url.set({ flag: v })} options={[{ value: "", label: "Any flag" }, { value: "review", label: "Needs human review" }]} />
        </FilterBar>
        {list.isPending ? (
          <TableSkeleton rows={5} label="Loading audits" />
        ) : list.isError ? (
          <div className="p-4"><ErrorPanel error={list.error} what="audits" onRetry={() => void list.refetch()} /></div>
        ) : rows.length === 0 ? (
          chips.length || needle ? (
            <EmptyState icon={Upload} title="No audits match these filters" body="Try different filters." action={<Button onClick={() => url.clear()}>Clear filters</Button>} />
          ) : (
            <EmptyState icon={Upload} title="No audits yet" body="Upload a recorded call to score it with the same rubric as your test runs." action={<LinkButton variant="primary" href="/audits/new">Upload recording</LinkButton>} secondary={<Link className="underline" href="/integrations">Send calls automatically with a webhook</Link>} />
          )
        ) : (
          <>
            <DataTable caption="Audits" columns={columns} rows={rows} rowKey={(r) => r.id} sort={sort} onSort={(n) => url.set({ sort: n })} />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>
    </>
  );
}
