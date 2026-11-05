"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel, Chip } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { SelectField, TextField } from "@/components/ui/field";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { RowMenu } from "@/components/ui/row-menu";
import { useToast } from "@/components/ui/toast";

type Role = "admin" | "member";
type User = { id: string; email: string; name: string; role: Role; disabled: boolean; created_at: string; last_login_at: string | null };

/** Users live behind /users on the API; the web proxy lets only admins through. */
async function users<T>(path: string, init?: { method: string; body: unknown }): Promise<T> {
  const res = await fetch(`/api/proxy/api/v1/users${path}`, {
    method: init?.method ?? "GET",
    headers: init ? { "content-type": "application/json" } : undefined,
    body: init ? JSON.stringify(init.body) : undefined,
  }).catch(() => null);
  if (!res) throw new Error("The API did not respond.");
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.error?.message ?? (typeof body?.error === "string" ? body.error : "The request failed."));
  return body as T;
}

const msg = (e: unknown) => (e instanceof Error ? e.message : "The request failed.");

function AddUser({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ name: "", email: "", password: "", role: "member" as Role });
  const [err, setErr] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => users<User>("", { method: "POST", body: { ...f, name: f.name.trim(), email: f.email.trim() } }),
    onSuccess: () => {
      onDone();
      close();
    },
    onError: (e) => setErr(msg(e)),
  });
  const close = () => {
    setF({ name: "", email: "", password: "", role: "member" });
    setErr(null);
    onClose();
  };
  const ok = f.name.trim() && f.email.includes("@") && f.password.length >= 10;
  return (
    <Dialog
      open={open}
      onClose={close}
      title="Add a user"
      footer={
        <>
          <Button onClick={close}>Cancel</Button>
          <Button variant="primary" loading={create.isPending} disabled={!ok} onClick={() => create.mutate()}>Add user</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {err && <Strip tone="error">{err}</Strip>}
        <TextField label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <TextField label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <TextField label="Temporary password" type="text" autoComplete="off" help="10 characters or more. Share it with them directly; they can be given a new one any time." value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <SelectField label="Role" help="Admins manage users and API keys. Members use everything else." value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </SelectField>
      </div>
    </Dialog>
  );
}

function ResetPassword({ user, onClose }: { user: User | null; onClose: () => void }) {
  const { toast } = useToast();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const reset = useMutation({
    mutationFn: () => users<User>(`/${user!.id}`, { method: "PATCH", body: { password: pw } }),
    onSuccess: () => {
      toast(`Password changed for ${user!.name}.`);
      close();
    },
    onError: (e) => setErr(msg(e)),
  });
  const close = () => {
    setPw("");
    setErr(null);
    onClose();
  };
  return (
    <Dialog
      open={!!user}
      onClose={close}
      title={`New password for ${user?.name ?? ""}`}
      footer={
        <>
          <Button onClick={close}>Cancel</Button>
          <Button variant="primary" loading={reset.isPending} disabled={pw.length < 10} onClick={() => reset.mutate()}>Change password</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {err && <Strip tone="error">{err}</Strip>}
        <TextField label="New password" type="text" autoComplete="off" help="10 characters or more. Their current sessions last until they expire." value={pw} onChange={(e) => setPw(e.target.value)} />
      </div>
    </Dialog>
  );
}

export function UsersPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [adding, setAdding] = useState(false);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [toDisable, setToDisable] = useState<User | null>(null);
  const q = useQuery({ queryKey: ["users"], queryFn: () => users<{ items: User[] }>("") });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["users"] });
  const patch = useMutation({
    mutationFn: ({ u, body }: { u: User; body: Partial<{ role: Role; disabled: boolean }> }) => users<User>(`/${u.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      setToDisable(null);
      refresh();
    },
    onError: (e) => {
      setToDisable(null);
      toast(`Could not change the user: ${msg(e)}`, { tone: "error" });
    },
  });
  const rows = q.data?.items ?? [];
  const columns: Column<User>[] = [
    { key: "name", header: "Name", cell: (u) => <span className="font-medium">{u.name}</span> },
    { key: "email", header: "Email", cell: (u) => <span className="text-muted">{u.email}</span> },
    { key: "role", header: "Role", cell: (u) => <Chip>{u.role === "admin" ? "Admin" : "Member"}</Chip> },
    { key: "status", header: "Status", hidePhone: true, cell: (u) => (u.disabled ? <span className="text-fail-fg">Disabled</span> : <span className="text-muted">Active</span>) },
    { key: "login", header: "Last sign-in", hidePhone: true, cell: (u) => (u.last_login_at ? <time dateTime={u.last_login_at} title={u.last_login_at} className="text-muted">{relativeTime(u.last_login_at)}</time> : <span className="text-subtle">never</span>) },
  ];
  return (
    <>
      <PageHeader
        eyebrow={q.isSuccess ? `${rows.filter((u) => !u.disabled).length} active` : ""}
        title="Users"
        description="Only admins see this page. There is no public sign-up: add people here and give them their password."
        actions={<Button variant="primary" onClick={() => setAdding(true)}>Add user</Button>}
      />
      <Panel bodyClassName="p-0" title="Accounts">
        {q.isPending ? (
          <TableSkeleton rows={3} label="Loading users" />
        ) : q.isError ? (
          <div className="p-4"><ErrorPanel error={q.error} what="users" onRetry={() => void q.refetch()} /></div>
        ) : rows.length === 0 ? (
          <EmptyState icon={Users} title="No users yet" body="Add the first person." action={<Button variant="primary" onClick={() => setAdding(true)}>Add user</Button>} />
        ) : (
          <DataTable
            caption="Users"
            columns={columns}
            rows={rows}
            rowKey={(u) => u.id}
            sort={null}
            onSort={() => undefined}
            actions={(u) => (
              <RowMenu
                label={`Actions for ${u.name}`}
                items={[
                  { label: u.role === "admin" ? "Make member" : "Make admin", onSelect: () => patch.mutate({ u, body: { role: u.role === "admin" ? "member" : "admin" } }) },
                  { label: "Set a new password", onSelect: () => setResetFor(u) },
                  u.disabled ? { label: "Enable", onSelect: () => patch.mutate({ u, body: { disabled: false } }) } : { label: "Disable", destructive: true, onSelect: () => setToDisable(u) },
                ]}
              />
            )}
          />
        )}
      </Panel>
      <AddUser open={adding} onClose={() => setAdding(false)} onDone={refresh} />
      <ResetPassword user={resetFor} onClose={() => setResetFor(null)} />
      <ConfirmDialog
        open={!!toDisable}
        onClose={() => setToDisable(null)}
        title="Disable user"
        body={`Disable ${toDisable?.name}? They can no longer sign in. A session already open lasts until it expires.`}
        confirmLabel="Disable"
        busy={patch.isPending}
        onConfirm={() => toDisable && patch.mutate({ u: toDisable, body: { disabled: true } })}
      />
    </>
  );
}
