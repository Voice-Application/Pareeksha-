"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { relativeTime } from "@/lib/format";
import { PageError, ErrorPanel, Strip, TableSkeleton, EmptyState, NotEnabled, isNotImplemented } from "@/components/ui/states";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, LoadMore, type Column } from "@/components/ui/data-table";
import { FilterSelect, Segmented, Switch, TextField } from "@/components/ui/field";
import { ConfirmDialog, Sheet } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { CircleCheck, CircleX, Clock, Minus, Plug } from "lucide-react";
import { CodeBlock } from "@/components/ops/code-block";
import { JsonSchemaForm } from "./json-schema-form";
import { Health } from "./integrations-page";

type Delivery = components["schemas"]["DeliveryOut"];

function DeliveryStatus({ s }: { s: Delivery["status"] }) {
  const Icon = s === "succeeded" ? CircleCheck : s === "failed" ? CircleX : s === "pending" ? Clock : Minus;
  return <span className={`inline-flex items-center gap-1.5 text-xs ${s === "failed" ? "text-fail-fg" : "text-muted"}`}><Icon size={14} strokeWidth={1.6} aria-hidden />{s}</span>;
}

function Deliveries({ id }: { id: string }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<Delivery | null>(null);
  const [confirm, setConfirm] = useState<Delivery | null>(null);
  const list = usePagedList<Delivery>(["deliveries", id], (cursor) => call(api.GET("/api/v1/integrations/{integration_id}/deliveries", { params: { path: { integration_id: id }, query: { limit: 50, cursor } } })));
  const redeliver = useMutation({
    mutationFn: (d: Delivery) => call(api.POST("/api/v1/integrations/{integration_id}/deliveries/{delivery_id}/redeliver", { params: { path: { integration_id: id, delivery_id: d.id } } })),
    onSuccess: () => { toast("Redelivery queued. It is idempotent: nothing is sent twice."); setConfirm(null); void qc.invalidateQueries({ queryKey: ["deliveries", id] }); },
    onError: (e) => { setConfirm(null); toast(isNotImplemented(e) ? "Redelivery is not available in this build yet." : `Could not redeliver: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error" }); },
  });
  const rows = list.items.filter((d) => !status || d.status === status);
  const columns: Column<Delivery>[] = [
    { key: "time", header: "Time", cell: (d) => <time dateTime={d.created_at} title={d.created_at} className="text-muted">{relativeTime(d.created_at)}</time> },
    { key: "event", header: "Event", mono: true, cell: (d) => <button type="button" className="underline-offset-2 hover:underline" onClick={() => setOpen(d)}>{d.event_id.slice(0, 8)}</button> },
    { key: "dir", header: "Direction", mono: true, hidePhone: true, cell: (d) => d.direction },
    { key: "status", header: "Status", cell: (d) => <DeliveryStatus s={d.status} /> },
    { key: "http", header: "HTTP", mono: true, hidePhone: true, cell: (d) => d.http_status ?? "-" },
    { key: "ext", header: "External id", mono: true, hidePhone: true, cell: (d) => d.external_id ?? "-" },
    { key: "attempts", header: "Attempts", mono: true, cell: (d) => d.attempts },
  ];
  if (list.isError) return isNotImplemented(list.error) ? <Panel><NotEnabled icon={Plug} what="The delivery log" error={list.error} /></Panel> : <ErrorPanel error={list.error} what="deliveries" onRetry={() => void list.refetch()} />;
  return (
    <Panel title="Deliveries" bodyClassName="p-0">
      <div className="border-b border-border p-3"><FilterSelect label="Status" value={status} onChange={setStatus} options={[{ value: "", label: "All statuses" }, ...["succeeded", "failed", "skipped", "pending"].map((s) => ({ value: s, label: s }))]} /></div>
      {list.isPending ? <TableSkeleton rows={4} /> : rows.length === 0 ? <EmptyState icon={Plug} title="No deliveries yet" body="Deliveries appear here when a matching event is sent or received." /> : (
        <>
          <DataTable caption="Deliveries" columns={columns} rows={rows} rowKey={(d) => d.id} sort={null} onSort={() => undefined} actions={(d) => (d.status === "failed" ? <Button className="h-6 px-2" onClick={() => setConfirm(d)}>Redeliver</Button> : null)} />
          <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={rows.length} />
        </>
      )}
      <Sheet open={!!open} onClose={() => setOpen(null)} title="Delivery">
        {open && (
          <div className="flex flex-col gap-3 text-sm">
            <dl className="grid grid-cols-2 gap-3"><div><dt className="eyebrow">Event id</dt><dd className="mono break-all">{open.event_id}</dd></div><div><dt className="eyebrow">Status</dt><dd><DeliveryStatus s={open.status} /></dd></div><div><dt className="eyebrow">HTTP</dt><dd className="mono">{open.http_status ?? "-"}</dd></div><div><dt className="eyebrow">Attempts</dt><dd className="mono">{open.attempts}</dd></div></dl>
            <div><p className="eyebrow mb-1">Response excerpt</p><CodeBlock label="response excerpt" text={open.response_excerpt || "(empty)"} max={500} /></div>
          </div>
        )}
      </Sheet>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} title="Redeliver" body="Idempotent. If it already succeeded, nothing is sent twice." confirmLabel="Redeliver" busy={redeliver.isPending} onConfirm={() => confirm && redeliver.mutate(confirm)} />
    </Panel>
  );
}

export function IntegrationDetail({ id }: { id: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [tab, setTab] = useState<"settings" | "deliveries">("settings");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const q = useQuery({ queryKey: ["integration", id], queryFn: () => call(api.GET("/api/v1/integrations/{integration_id}", { params: { path: { integration_id: id } } })) });
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: () => call(api.GET("/api/v1/integrations/connectors")) });
  const [name, setName] = useState<string | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [secrets, setSecrets] = useState<Record<string, unknown>>({});
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const info = (Array.isArray(connectors.data) ? connectors.data : []).find((c) => c.name === q.data?.connector);

  const save = useMutation({
    mutationFn: () => call(api.PATCH("/api/v1/integrations/{integration_id}", { params: { path: { integration_id: id } }, body: { name: name ?? undefined, config: config ?? undefined, enabled: enabled ?? undefined, secrets: Object.fromEntries(Object.entries(secrets).filter(([, v]) => v).map(([k, v]) => [k, String(v)])) } })),
    onSuccess: () => { toast("Saved."); setSecrets({}); void qc.invalidateQueries({ queryKey: ["integration", id] }); void qc.invalidateQueries({ queryKey: ["integrations"] }); },
  });
  const test = useMutation({
    mutationFn: () => call(api.POST("/api/v1/integrations/{integration_id}/test", { params: { path: { integration_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["integration", id] }),
  });
  const del = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/integrations/{integration_id}", { params: { path: { integration_id: id } } })),
    onSuccess: () => { toast("Integration deleted."); void qc.invalidateQueries({ queryKey: ["integrations"] }); router.push("/integrations"); },
    onError: (e) => { setConfirmDelete(false); toast(`Could not delete: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error" }); },
  });

  if (q.isError) return <PageError error={q.error} onRetry={() => void q.refetch()} backHref="/integrations" backLabel="Back to integrations" />;
  if (q.isPending) return <TableSkeleton rows={3} />;
  const i = q.data;
  const secretKeys = Object.keys(((info?.secrets_schema as { properties?: Record<string, unknown> } | undefined)?.properties) ?? {});
  return (
    <>
      <PageHeader eyebrow={`Integration | ${i.connector} | ${i.direction}`} title={i.name} description={<Health i={i} />} actions={<Segmented hideLabel label="Section" value={tab} onChange={setTab} options={[{ value: "settings", label: "Settings" }, { value: "deliveries", label: "Deliveries" }]} />} />
      {tab === "deliveries" ? (
        <Deliveries id={id} />
      ) : (
        <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
          <Panel title="Settings">
            <div className="flex max-w-[520px] flex-col gap-4">
              {save.isError && <Strip tone="error">{save.error instanceof ApiError ? save.error.userMessage() : "The request failed."}</Strip>}
              <TextField label="Name" value={name ?? i.name} onChange={(e) => setName(e.target.value)} />
              <Switch label="Enabled" checked={enabled ?? i.enabled} onChange={setEnabled} />
              {info && <JsonSchemaForm schema={info.config_schema} values={config ?? (i.config as Record<string, unknown>)} onChange={setConfig} />}
              {info && secretKeys.length > 0 && <JsonSchemaForm schema={info.secrets_schema} values={secrets} onChange={setSecrets} secret setKeys={i.secrets_set ? secretKeys : []} />}
              {i.inbound_url && <div><p className="mb-1 text-sm font-medium">Inbound URL</p><code className="mono block break-all rounded-sm bg-sunken p-2 text-xs">{i.inbound_url}</code></div>}
              <div><Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save</Button></div>
            </div>
          </Panel>
          <div className="flex flex-col gap-6">
            <Panel title="Test connection">
              {test.isError && <Strip tone="error">{isNotImplemented(test.error) ? "Testing is not available in this build yet." : test.error instanceof ApiError ? test.error.userMessage() : "The request failed."}</Strip>}
              {test.data && <Strip tone={test.data.ok ? "warn" : "error"}>{test.data.ok ? "Connected. " : "Failed. "}{test.data.detail}</Strip>}
              <div className="mt-3"><Button loading={test.isPending} onClick={() => test.mutate()}>Test connection</Button></div>
            </Panel>
            <Panel title="Danger zone">
              <p className="mb-3 text-sm text-muted">Deleting keeps past deliveries for audit.</p>
              <Button variant="destructive" onClick={() => setConfirmDelete(true)}>Delete integration</Button>
            </Panel>
          </div>
        </div>
      )}
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete integration" body={`Delete "${i.name}"? Deliveries are kept for audit.`} confirmLabel="Delete" busy={del.isPending} onConfirm={() => del.mutate()} />
    </>
  );
}
