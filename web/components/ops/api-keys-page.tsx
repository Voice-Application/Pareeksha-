"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { TextField } from "@/components/ui/field";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { RowMenu } from "@/components/ui/row-menu";
import { useToast } from "@/components/ui/toast";
import { CodeBlock, CopyField } from "./code-block";

type Key = components["schemas"]["ApiKeyOut"];
type Scope = Key["scopes"][number];
const SCOPES: { id: Scope; text: string }[] = [
  { id: "read", text: "Read data" },
  { id: "runs:write", text: "Create and cancel runs" },
  { id: "audits:write", text: "Upload and audit calls" },
  { id: "admin", text: "Everything, including API keys and the DLQ" },
];

/** Create dialog that turns into the one-time reveal. The key lives in component state only and is dropped on close. */
function CreateKey({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Scope[]>(["read"]);
  const [key, setKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => call(api.POST("/api/v1/api-keys", { body: { name: name.trim(), scopes: scopes.includes("admin") ? ["admin"] : scopes } })),
    onSuccess: (r) => {
      setKey(r.key);
      onCreated();
    },
    onError: (e) => setErr(e instanceof ApiError && e.status === 0 ? "We could not confirm the key was created. Check the list before trying again." : e instanceof ApiError ? e.userMessage() : "The request failed."),
  });
  const close = () => {
    setKey(null);
    setName("");
    setScopes(["read"]);
    setCopied(false);
    setErr(null);
    onClose();
  };
  const toggle = (s: Scope) => setScopes((cur) => (s === "admin" ? (cur.includes("admin") ? ["read"] : ["admin"]) : cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  const admin = scopes.includes("admin");
  return (
    <Dialog
      open={open}
      onClose={key ? () => undefined : close}
      title={key ? "Copy your new key" : "Create API key"}
      footer={
        key ? (
          <Button variant="primary" disabled={!copied} onClick={close}>Done</Button>
        ) : (
          <>
            <Button onClick={close}>Cancel</Button>
            <Button variant="primary" loading={create.isPending} disabled={!name.trim() || scopes.length === 0} onClick={() => create.mutate()}>Create key</Button>
          </>
        )
      }
    >
      {key ? (
        <div className="flex flex-col gap-3">
          <Strip tone="warn">This is the only time you will see this key. Store it in a secret manager.</Strip>
          <CopyField value={key} label="New API key" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={copied} onChange={(e) => setCopied(e.target.checked)} />
            I have copied the key
          </label>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {err && <Strip tone="error">{err}</Strip>}
          <TextField label="Name" help="Where will this be used? For example github-actions" value={name} onChange={(e) => setName(e.target.value)} />
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">Scopes</legend>
            {SCOPES.map((s) => (
              <label key={s.id} className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={scopes.includes(s.id) || (admin && s.id !== "admin")} disabled={admin && s.id !== "admin"} onChange={() => toggle(s.id)} />
                <span>
                  <span className="mono">{s.id}</span> <span className="text-muted">{s.text}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </div>
      )}
    </Dialog>
  );
}

export function ApiKeysPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [creating, setCreating] = useState(false);
  const [toRevoke, setToRevoke] = useState<Key | null>(null);
  const [showRevoked, setShowRevoked] = useState(false);
  const q = useQuery({ queryKey: ["api-keys"], queryFn: () => call(api.GET("/api/v1/api-keys")) });
  const revoke = useMutation({
    mutationFn: (k: Key) => call(api.DELETE("/api/v1/api-keys/{api_key_id}", { params: { path: { api_key_id: k.id } } })),
    onSuccess: () => {
      toast("Key revoked.");
      setToRevoke(null);
      void qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (e, k) => {
      setToRevoke(null);
      if (e instanceof ApiError && e.status === 404) {
        void qc.invalidateQueries({ queryKey: ["api-keys"] });
        return;
      }
      toast(`Could not revoke: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => revoke.mutate(k) } });
    },
  });
  const all = q.data?.items ?? [];
  const active = all.filter((k) => !k.revoked_at);
  const rows = showRevoked ? all.filter((k) => k.revoked_at) : active;
  const columns: Column<Key>[] = [
    { key: "name", header: "Name", cell: (k) => <span className="inline-flex items-center gap-2 font-medium">{k.name}{k.name === "demo" && <Chip title="Created by the seed script. Revoke before sharing the instance.">demo</Chip>}</span> },
    { key: "prefix", header: "Prefix", mono: true, cell: (k) => k.prefix },
    {
      key: "scopes",
      header: "Scopes",
      hidePhone: true,
      cell: (k) => (
        <span className="flex flex-wrap gap-1">
          {k.scopes.map((s) => (
            <Chip key={s} mono title={s === "admin" ? "Full access" : undefined}>
              {s === "admin" && <TriangleAlert size={12} strokeWidth={1.6} aria-label="full access" role="img" />}
              {s}
            </Chip>
          ))}
        </span>
      ),
    },
    { key: "used", header: showRevoked ? "Revoked" : "Last used", cell: (k) => { const v = showRevoked ? k.revoked_at : k.last_used_at; return v ? <time dateTime={v} title={v} className="text-muted">{relativeTime(v)}</time> : <span className="text-subtle">never</span>; } },
    { key: "created", header: "Created", hidePhone: true, cell: (k) => <time dateTime={k.created_at} title={k.created_at} className="text-muted">{relativeTime(k.created_at)}</time> },
  ];
  return (
    <>
      <PageHeader
        eyebrow={q.isSuccess ? `${active.length} active key${active.length === 1 ? "" : "s"}` : ""}
        title="API keys"
        description="Use a key with the SDK, the CLI or the GitHub Action. The full key is shown once, when you create it."
        actions={<Button variant="primary" onClick={() => setCreating(true)}>Create key</Button>}
      />
      <Panel
        bodyClassName="p-0"
        title={showRevoked ? "Revoked keys" : "Active keys"}
        aux={<Button variant="ghost" onClick={() => setShowRevoked((v) => !v)}>{showRevoked ? "Show active" : "Show revoked"}</Button>}
      >
        {q.isPending ? (
          <TableSkeleton rows={3} label="Loading API keys" />
        ) : q.isError ? (
          <div className="p-4"><ErrorPanel error={q.error} what="API keys" onRetry={() => void q.refetch()} /></div>
        ) : rows.length === 0 ? (
          <EmptyState icon={KeyRound} title={showRevoked ? "No revoked keys" : "No API keys yet"} body={showRevoked ? "Keys you revoke are listed here with the date." : "Create one to use the SDK, CLI or GitHub Action."} action={!showRevoked && <Button variant="primary" onClick={() => setCreating(true)}>Create key</Button>} />
        ) : (
          <DataTable
            caption="API keys"
            columns={columns}
            rows={rows}
            rowKey={(k) => k.id}
            sort={null}
            onSort={() => undefined}
            actions={showRevoked ? undefined : (k) => <RowMenu label={`Actions for ${k.name}`} items={[{ label: "Revoke", destructive: true, onSelect: () => setToRevoke(k) }]} />}
          />
        )}
      </Panel>
      <div className="mt-6">
        <Panel title="How to use">
          <CodeBlock label="CLI login" text={"pareeksha login --key pk_live_...\nexport PAREEKSHA_API_KEY=pk_live_..."} />
        </Panel>
      </div>
      <CreateKey open={creating} onClose={() => setCreating(false)} onCreated={() => void qc.invalidateQueries({ queryKey: ["api-keys"] })} />
      <ConfirmDialog
        open={!!toRevoke}
        onClose={() => setToRevoke(null)}
        title="Revoke key"
        body={`Revoke "${toRevoke?.name}"? Anything using it stops working immediately.`}
        confirmLabel="Revoke key"
        busy={revoke.isPending}
        onConfirm={() => toRevoke && revoke.mutate(toRevoke)}
      />
    </>
  );
}
