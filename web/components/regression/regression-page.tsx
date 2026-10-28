"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, NotEnabled, isNotImplemented, Strip, TableSkeleton } from "@/components/ui/states";
import { FilterSelect } from "@/components/ui/field";
import { ScoreChip, TagChip, VerdictBadge } from "@/components/ui/measure";

type Test = components["schemas"]["RegressionTestOut"];

export function RegressionPage() {
  const url = useUrlState();
  const router = useRouter();
  const [runError, setRunError] = useState<string | null>(null);
  const agents = useQuery({ queryKey: ["agents", "options"], queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 100 } } })) });
  const agentId = url.get("agent") || agents.data?.items?.find((a) => !a.archived)?.id || "";
  const tests = useQuery({ queryKey: ["regression-tests", agentId], enabled: !!agentId, retry: false, queryFn: () => call(api.GET("/api/v1/regression-tests", { params: { query: { agent_id: agentId } } })) });
  const suites = useQuery({ queryKey: ["runs", "regression", agentId], enabled: !!agentId, queryFn: () => call(api.GET("/api/v1/runs", { params: { query: { agent_id: agentId, kind: "regression", limit: 10 } } })) });
  const run = useMutation({
    mutationFn: () => call(api.POST("/api/v1/runs:regression", { body: { agent_id: agentId, name: `Regression ${new Date().toISOString().slice(0, 10)}`, statuses: ["blocking"], confirm_over_budget: false } as never })),
    onSuccess: (r) => router.push(`/runs/${r.id}`),
    onError: (e) => setRunError(isNotImplemented(e) ? "The regression suite cannot run in this build yet." : e instanceof ApiError ? e.userMessage() : "The request failed."),
  });
  const items = tests.data?.items ?? [];
  const blocking = items.filter((t) => t.status === "blocking");
  const last = suites.data?.items?.[0];
  const failedBlocking = blocking.filter((t) => t.last_passed === false);
  const title = last?.summary?.suite_passed === false ? `Last suite run failed ${failedBlocking.length || "some"} of ${blocking.length} blocking tests` : last?.summary?.suite_passed ? `All ${blocking.length} blocking tests passed` : "No suite run yet";

  const columns: Column<Test>[] = [
    { key: "scenario", header: "Name (scenario)", cell: (t) => <span className="font-medium">{t.scenario_title}</span> },
    { key: "type", header: "Failure type", cell: (t) => <TagChip tag={t.failure_type} /> },
    { key: "status", header: "Status", mono: true, cell: (t) => t.status },
    { key: "baseline", header: "Baseline", mono: true, cell: (t) => t.baseline_score },
    { key: "tol", header: "Tol", mono: true, hidePhone: true, cell: (t) => t.tolerance },
    { key: "score", header: "Last score", cell: (t) => <ScoreChip score={t.last_score} /> },
    { key: "result", header: "Last result", cell: (t) => <span title={t.last_score != null ? `${t.last_score} against ${t.baseline_score} - ${t.tolerance} = ${t.baseline_score - t.tolerance}` : undefined}><VerdictBadge verdict={t.last_passed == null ? null : t.last_passed ? "pass" : "fail"} /></span> },
    { key: "source", header: "Source call", mono: true, hidePhone: true, cell: (t) => (t.source_call_id ? <Link className="underline-offset-2 hover:underline" href={`/calls/${t.source_call_id}`}>{t.source_call_id.slice(0, 8)}</Link> : <span className="text-subtle">-</span>) },
  ];
  return (
    <>
      <PageHeader
        eyebrow={tests.isSuccess ? `${blocking.length} blocking, ${items.filter((t) => t.status === "scheduled").length} scheduled, ${items.filter((t) => t.status === "manual").length} manual` : "Regression"}
        title={tests.isError && isNotImplemented(tests.error) ? "Regression" : title}
        description="Failed calls you promoted become tests that future runs must not fail."
        actions={<>
          {(agents.data?.items?.length ?? 0) > 1 && <FilterSelect label="Agent" value={agentId} onChange={(v) => url.set({ agent: v })} options={(agents.data?.items ?? []).filter((a) => !a.archived).map((a) => ({ value: a.id, label: a.name }))} />}
          <Button variant="primary" loading={run.isPending} disabled={blocking.length === 0} title={blocking.length === 0 ? "No blocking tests to run" : undefined} onClick={() => { setRunError(null); run.mutate(); }}>Run regression suite</Button>
        </>}
      />
      {runError && <div className="mb-6"><Strip tone="error">{runError}</Strip></div>}
      <Panel bodyClassName="p-0" title="Regression tests">
        {tests.isError ? (
          isNotImplemented(tests.error) ? <NotEnabled icon={FlaskConical} what="Regression tests" error={tests.error} /> : <div className="p-4"><ErrorPanel error={tests.error} what="regression tests" onRetry={() => void tests.refetch()} /></div>
        ) : agents.isPending || tests.isPending ? (
          <TableSkeleton rows={5} />
        ) : items.length === 0 ? (
          <EmptyState icon={FlaskConical} title="No regression tests yet" body="Promote a failed call and it becomes a test that future runs must not fail." action={<Link className="inline-flex h-8 items-center rounded-sm bg-accent px-3 text-sm text-accent-on" href="/runs">Open failed calls</Link>} />
        ) : (
          <DataTable caption="Regression tests" columns={columns} rows={items} rowKey={(t) => t.id} sort={null} onSort={() => undefined} />
        )}
      </Panel>
    </>
  );
}
