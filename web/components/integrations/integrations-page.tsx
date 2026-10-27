"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Minus, Plug } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { usePagedList } from "@/lib/hooks/use-paged-list";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, LoadMore, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { NumberField, SelectField, Switch, TextField } from "@/components/ui/field";
import { Sheet } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { CopyField } from "@/components/ops/code-block";
import { JsonSchemaForm } from "./json-schema-form";

export type Integration = components["schemas"]["IntegrationOut"];
const PLANNED = ["Salesforce", "Zoho", "LeadSquared", "Freshdesk", "Exotel", "Slack"];

export function Health({ i }: { i: Integration }) {
  if (i.last_test_ok === true) return <span className="inline-flex items-center gap-1 text-pass-fg"><CircleCheck size={14} strokeWidth={1.6} aria-hidden />ok</span>;
  if (i.last_test_ok === false) return <span className="inline-flex items-center gap-1 text-fail-fg"><CircleX size={14} strokeWidth={1.6} aria-hidden />test failed</span>;
  return <span className="inline-flex items-center gap-1 text-subtle"><Minus size={14} strokeWidth={1.6} aria-hidden />untested</span>;
}

function AddSheet({ open, onClose, connectors }: { open: boolean; onClose: () => void; connectors: components["schemas"]["ConnectorInfo"][] }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [connector, setConnector] = useState("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [secrets, setSecrets] = useState<Record<string, unknown>>({});
  const [events, setEvents] = useState("evaluation.completed");
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [below, setBelow] = useState("");
  const [reveal, setReveal] = useState<Integration | null>(null);
  const [copied, setCopied] = useState(false);
  const info = connectors.find((c) => c.name === connector);

  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/v1/integrations", {
          body: {
            connector,
            name: name.trim(),
            config,
            secrets: Object.fromEntries(Object.entries(secrets).filter(([, v]) => v).map(([k, v]) => [k, String(v)])),
            event_filter: { events: events.split(",").map((s) => s.trim()).filter(Boolean), only_failed: onlyFailed, min_score_below: below === "" ? null : Number(below) },
            enabled: true,
          },
        }),
      ),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["integrations"] });
      toast(`Saved ${r.name}.`);
      if (r.signing_secret) setReveal(r);
      else close();
    },
  });
  function close() {
    setReveal(null);
    setCopied(false);
    setConnector("");
    setName("");
    setConfig({});
    setSecrets({});
    onClose();
  }
  return (
    <Sheet
      open={open}
      onClose={reveal && !copied ? () => undefined : close}
      title={reveal ? "Copy your signing secret" : "Add integration"}
      footer={
        reveal ? (
          <Button variant="primary" disabled={!copied} onClick={close}>Close</Button>
        ) : (
          <div className="flex justify-end gap-2">
            <Button onClick={close}>Cancel</Button>
            <Button variant="primary" loading={save.isPending} disabled={!connector || !name.trim()} onClick={() => save.mutate()}>Save</Button>
          </div>
        )
      }
    >
      {reveal ? (
        <div className="flex flex-col gap-3">
          <Strip tone="warn">Shown once. Store the signing secret now.</Strip>
          {reveal.inbound_url && <div><p className="mb-1 text-sm font-medium">Inbound URL</p><CopyField value={reveal.inbound_url} label="Inbound URL" /></div>}
          <div><p className="mb-1 text-sm font-medium">Signing secret</p><CopyField value={reveal.signing_secret ?? ""} label="Signing secret" /></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={copied} onChange={(e) => setCopied(e.target.checked)} />I copied it</label>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {save.isError && <Strip tone="error">{save.error instanceof ApiError ? save.error.userMessage() : "The request failed."}</Strip>}
          <SelectField label="Connector" value={connector} onChange={(e) => { setConnector(e.target.value); setConfig({}); setSecrets({}); }}>
            <option value="">Choose a connector</option>
            {connectors.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.direction})</option>)}
          </SelectField>
          {info && (
            <>
              <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
              <JsonSchemaForm schema={info.config_schema} values={config} onChange={setConfig} />
              <JsonSchemaForm schema={info.secrets_schema} values={secrets} onChange={setSecrets} secret />
              <fieldset className="flex flex-col gap-3 border-t border-border pt-4">
                <legend className="eyebrow mb-1">Event filter</legend>
                <TextField label="Events" help="Comma separated, for example evaluation.completed" value={events} onChange={(e) => setEvents(e.target.value)} />
                <Switch label="Only failed calls" checked={onlyFailed} onChange={setOnlyFailed} />
                <NumberField label="Only scores below" help="Optional" min={0} max={100} value={below} onChange={(e) => setBelow(e.target.value)} />
              </fieldset>
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}

export function IntegrationsPage() {
  const [adding, setAdding] = useState(false);
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: () => call(api.GET("/api/v1/integrations/connectors")) });
  const list = usePagedList<Integration>(["integrations"], (cursor) => call(api.GET("/api/v1/integrations", { params: { query: { limit: 50, cursor } } })));
  const cs = useMemo(() => (Array.isArray(connectors.data) ? connectors.data : []), [connectors.data]);
  const columns: Column<Integration>[] = [
    { key: "name", header: "Name", cell: (i) => <Link href={`/integrations/${i.id}`} className="font-medium underline-offset-2 hover:underline">{i.name}</Link> },
    { key: "connector", header: "Connector", mono: true, cell: (i) => i.connector },
    { key: "direction", header: "Direction", mono: true, hidePhone: true, cell: (i) => i.direction },
    { key: "events", header: "Events", mono: true, hidePhone: true, cell: (i) => (i.event_filter?.events?.length ? i.event_filter.events.join(", ") : <span className="text-subtle">all</span>) },
    { key: "enabled", header: "State", cell: (i) => (i.enabled ? "enabled" : <span className="text-subtle">disabled</span>) },
    { key: "test", header: "Last test", hidePhone: true, cell: (i) => (i.last_test_at ? <time dateTime={i.last_test_at} className="text-muted">{relativeTime(i.last_test_at)}</time> : <span className="text-subtle">never</span>) },
    { key: "health", header: "Health", cell: (i) => <Health i={i} /> },
  ];
  return (
    <>
      <PageHeader eyebrow={list.isSuccess ? `${list.items.length} connected` : ""} title="Integrations" description="Send evaluated calls to your CRM, or receive recordings from your telephony with a signed webhook." actions={<Button variant="primary" disabled={cs.length === 0} title={cs.length === 0 ? "No connectors are registered on the API" : undefined} onClick={() => setAdding(true)}>Add integration</Button>} />
      <Panel bodyClassName="p-0">
        {list.isPending ? (
          <TableSkeleton rows={3} label="Loading integrations" />
        ) : list.isError ? (
          <div className="p-4"><ErrorPanel error={list.error} what="integrations" onRetry={() => void list.refetch()} /></div>
        ) : list.items.length === 0 ? (
          <EmptyState icon={Plug} title="No integrations yet" body="An integration sends evaluation results to a CRM, or brings recorded calls in through a webhook." action={<Button variant="primary" disabled={cs.length === 0} onClick={() => setAdding(true)}>Add integration</Button>} />
        ) : (
          <>
            <DataTable caption="Integrations" columns={columns} rows={list.items} rowKey={(i) => i.id} sort={null} onSort={() => undefined} />
            <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} shown={list.items.length} />
          </>
        )}
      </Panel>
      <div className="mt-6">
        <Panel title="Available connectors">
          {connectors.isPending ? (
            <p className="text-sm text-subtle">Loading connectors…</p>
          ) : connectors.isError ? (
            <ErrorPanel error={connectors.error} what="connectors" onRetry={() => void connectors.refetch()} />
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {cs.length === 0 && <li className="text-muted">The API reports no registered connectors.</li>}
              {cs.map((c) => (
                <li key={c.name} className="flex items-center gap-2"><span className="mono font-medium">{c.name}</span><Chip mono>{c.direction}</Chip><span className="text-muted">subscribes to {(c.subscribes_to ?? []).join(", ") || "nothing"}</span></li>
              ))}
              <li className="flex flex-wrap items-center gap-2 border-t border-border pt-2 text-muted">{PLANNED.map((p) => <span key={p} className="inline-flex items-center gap-1">{p}<Chip>Planned</Chip></span>)}</li>
            </ul>
          )}
        </Panel>
      </div>
      <AddSheet open={adding} onClose={() => setAdding(false)} connectors={cs} />
    </>
  );
}
