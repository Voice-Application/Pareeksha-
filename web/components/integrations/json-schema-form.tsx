"use client";

import { NumberField, SelectField, Switch, TextField } from "@/components/ui/field";
import { Button } from "@/components/ui/button";
import { useState } from "react";

type Prop = { type?: string; title?: string; description?: string; enum?: string[]; default?: unknown; format?: string };
type Schema = { properties?: Record<string, Prop>; required?: string[] };

/** Renders a connector's `config_schema` / `secrets_schema` (GET /integrations/connectors). Secrets are write-only. */
export function JsonSchemaForm({ schema, values, onChange, secret = false, setKeys = [], errors = {} }: { schema: Record<string, unknown>; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; secret?: boolean; setKeys?: string[]; errors?: Record<string, string> }) {
  const s = schema as Schema;
  const props = Object.entries(s.properties ?? {});
  const required = new Set(s.required ?? []);
  const set = (k: string, v: unknown) => onChange({ ...values, [k]: v });
  return (
    <>
      {props.map(([k, p]) => {
        const label = `${p.title ?? k}${required.has(k) ? "" : " (optional)"}`;
        const err = errors[k];
        if (secret) return <SecretField key={k} label={label} help={p.description} alreadySet={setKeys.includes(k)} value={String(values[k] ?? "")} onChange={(v) => set(k, v)} error={err} />;
        if (p.enum) return (
          <SelectField key={k} label={label} help={p.description} value={String(values[k] ?? p.default ?? p.enum[0])} onChange={(e) => set(k, e.target.value)} error={err}>
            {p.enum.map((o) => <option key={o} value={o}>{o}</option>)}
          </SelectField>
        );
        if (p.type === "boolean") return <Switch key={k} label={label} help={p.description} checked={Boolean(values[k] ?? p.default ?? false)} onChange={(v) => set(k, v)} />;
        if (p.type === "integer" || p.type === "number") return <NumberField key={k} label={label} help={p.description} value={String(values[k] ?? p.default ?? "")} onChange={(e) => set(k, e.target.value === "" ? undefined : Number(e.target.value))} error={err} />;
        return <TextField key={k} label={label} help={p.description} value={String(values[k] ?? p.default ?? "")} onChange={(e) => set(k, e.target.value)} error={err} />;
      })}
    </>
  );
}

/** Write-only: shows "Set" with a Replace button once saved, never the value. */
function SecretField({ label, help, alreadySet, value, onChange, error }: { label: string; help?: string; alreadySet: boolean; value: string; onChange: (v: string) => void; error?: string }) {
  const [replacing, setReplacing] = useState(false);
  if (alreadySet && !replacing)
    return (
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium">{label}</span>
        <div className="flex items-center gap-2">
          <span className="mono inline-flex h-8 items-center rounded-sm border border-border bg-sunken px-3 text-sm text-muted">Set</span>
          <Button onClick={() => setReplacing(true)}>Replace</Button>
        </div>
      </div>
    );
  return <TextField label={label} help={help} type="password" autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)} error={error} />;
}
