"use client";

import { useId, useRef, useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes, type KeyboardEvent } from "react";
import { CircleAlert, Plus, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export const controlClass =
  "h-9 w-full rounded-sm border border-border-strong bg-surface px-3 text-sm text-fg placeholder:text-subtle transition-[border-color] duration-150 hover:border-fg disabled:cursor-not-allowed disabled:bg-sunken disabled:text-subtle disabled:opacity-55 disabled:hover:border-border-strong aria-[invalid=true]:border-fail";

/** Label above, help text below, error text with icon below (00-shared 4). `id` ties label, help and error to the control. */
export function Field({
  label,
  id,
  help,
  error,
  children,
  className,
  required,
}: {
  label: string;
  id: string;
  help?: ReactNode;
  error?: string | null;
  children: ReactNode;
  className?: string;
  required?: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {required && <span className="ml-1 text-subtle" aria-hidden>*</span>}
      </label>
      {children}
      {help && !error && (
        <p id={`${id}-help`} className="text-xs text-subtle">
          {help}
        </p>
      )}
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  );
}

/** Inline field error with an icon. */
export function FieldError({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p id={id} className="flex items-start gap-1 text-xs text-fail-fg">
      <CircleAlert size={14} strokeWidth={1.6} className="mt-px shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** aria-describedby target: the error when present, else the help text. */
function describedBy(id: string, hasHelp: boolean, error?: string | null) {
  return error ? `${id}-error` : hasHelp ? `${id}-help` : undefined;
}

type WithField = { label: string; help?: ReactNode; error?: string | null; fieldClassName?: string };

/** Labelled text input wired to its help and error text. */
export function TextField({ label, help, error, fieldClassName, id: idProp, className, ...rest }: WithField & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Field label={label} id={id} help={help} error={error} className={fieldClassName} required={rest.required}>
      <input id={id} className={cn(controlClass, className)} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, !!help, error)} {...rest} />
    </Field>
  );
}

/** TextField for numbers, with a numeric keyboard and mono digits. */
export function NumberField({ label, help, error, fieldClassName, id: idProp, className, ...rest }: WithField & InputHTMLAttributes<HTMLInputElement>) {
  return <TextField type="number" inputMode="numeric" className={cn("mono", className)} label={label} help={help} error={error} fieldClassName={fieldClassName} id={idProp} {...rest} />;
}

/** Labelled textarea wired to its help and error text. */
export function TextAreaField({
  label,
  help,
  error,
  fieldClassName,
  id: idProp,
  className,
  ...rest
}: WithField & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Field label={label} id={id} help={help} error={error} className={fieldClassName} required={rest.required}>
      <textarea
        id={id}
        className={cn(controlClass, "h-auto min-h-[88px] py-1.5 leading-5", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, !!help, error)}
        {...rest}
      />
    </Field>
  );
}

/** Labelled native select wired to its help and error text. */
export function SelectField({
  label,
  help,
  error,
  fieldClassName,
  id: idProp,
  className,
  children,
  ...rest
}: WithField & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Field label={label} id={id} help={help} error={error} className={fieldClassName} required={rest.required}>
      <select id={id} className={cn(controlClass, className)} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, !!help, error)} {...rest}>
        {children}
      </select>
    </Field>
  );
}

/** Small select without a field wrapper, for FilterBar. */
export function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={cn(controlClass, "w-auto min-w-[120px]")}>
      <option value="">{label}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export type SegmentOption<T extends string | number> = { value: T; label: string; disabled?: boolean; hint?: string };

/** Mutually exclusive 2-5 options. Radiogroup semantics: arrow keys move and select, Tab leaves the group. */
export function Segmented<T extends string | number>({
  label,
  value,
  onChange,
  options,
  help,
  disabled,
  hideLabel,
}: {
  hideLabel?: boolean;
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: SegmentOption<T>[];
  help?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0);

  /** Arrow keys move to and select the next enabled option, wrapping around. */
  function onKey(e: KeyboardEvent, idx: number) {
    const pos = enabled.indexOf(idx);
    let target: number | undefined;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") target = enabled[(pos + 1) % enabled.length];
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") target = enabled[(pos - 1 + enabled.length) % enabled.length];
    if (target !== undefined) {
      e.preventDefault();
      onChange(options[target].value);
      refs.current[target]?.focus();
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <span id={id} className={hideLabel ? "sr-only" : "text-sm font-medium"}>
        {label}
      </span>
      <div role="radiogroup" aria-labelledby={id} className="inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-md bg-sunken p-0.5">
        {options.map((o, i) => {
          const selected = o.value === value;
          return (
            <button
              key={String(o.value)}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected || (!options.some((x) => x.value === value) && i === enabled[0]) ? 0 : -1}
              disabled={o.disabled || disabled}
              title={o.hint}
              onKeyDown={(e) => onKey(e, i)}
              onClick={() => onChange(o.value)}
              className={cn(
                "h-8 rounded-pill px-3.5 text-sm transition-colors active:translate-y-px disabled:cursor-not-allowed disabled:text-subtle disabled:opacity-55",
                selected ? "bg-surface font-medium text-fg outline outline-1 -outline-offset-1 outline-border" : "text-muted hover:text-fg",
              )}
            >
              {o.label}
            </button>
          );
        })}
      </div>
      {help && <p className="text-xs text-subtle">{help}</p>}
    </div>
  );
}

/** Labelled on/off switch with optional help text. */
export function Switch({ label, checked, onChange, help, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; help?: ReactNode; disabled?: boolean }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-3">
        <button
          id={id}
          type="button"
          role="switch"
          aria-checked={checked}
          aria-describedby={help ? `${id}-help` : undefined}
          disabled={disabled}
          onClick={() => onChange(!checked)}
          className={cn(
            "relative h-5 w-9 shrink-0 border transition-colors disabled:cursor-not-allowed disabled:opacity-55",
            checked ? "border-accent bg-accent" : "border-border-strong bg-sunken",
          )}
          style={{ borderRadius: "var(--radius-pill)" }}
        >
          <span
            aria-hidden
            className={cn("absolute top-0.5 left-0.5 h-3.5 w-3.5 transition-transform duration-150 ease-out", checked ? "translate-x-4" : "translate-x-0")}
            style={{ borderRadius: "var(--radius-pill)", background: checked ? "var(--accent-on)" : "var(--fg-muted)" }}
          />
        </button>
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <span className="text-xs text-subtle">{checked ? "on" : "off"}</span>
      </div>
      {help && (
        <p id={`${id}-help`} className="text-xs text-subtle">
          {help}
        </p>
      )}
    </div>
  );
}

/** Labelled range input. */
export function SliderField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  format = (v) => String(v),
  disabled,
  help,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  format?: (v: number) => string;
  disabled?: boolean;
  help?: ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <output htmlFor={id} className="mono text-sm">
          {format(value)}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-8 w-full cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
        style={{ accentColor: "var(--accent)" }}
        aria-describedby={help ? `${id}-help` : undefined}
      />
      {help && (
        <p id={`${id}-help`} className="text-xs text-subtle">
          {help}
        </p>
      )}
    </div>
  );
}

/** Tag input: Enter or comma adds, Backspace on empty input removes the last, each tag has a remove button. */
export function TagInput({
  label,
  value,
  onChange,
  suggestions = [],
  help,
  placeholder,
  error,
  mono,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  suggestions?: string[];
  help?: ReactNode;
  placeholder?: string;
  error?: string | null;
  mono?: boolean;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  /** Add the trimmed draft as a tag unless empty or a duplicate, then clear it. */
  function commit(raw: string) {
    const t = raw.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setDraft("");
  }
  const remaining = suggestions.filter((s) => !value.includes(s));
  return (
    <Field label={label} id={id} help={help} error={error}>
      <div className="flex min-h-9 flex-wrap items-center gap-1 rounded-sm border border-border-strong bg-surface px-1.5 py-1 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[color:var(--focus-ring)]">
        {value.map((t) => (
          <span key={t} className={cn("inline-flex h-6 items-center gap-1 rounded-xs border border-border bg-sunken pl-2 pr-0.5 text-xs", mono && "mono")}>
            {t}
            <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))} className="flex h-5 w-5 items-center justify-center rounded-xs text-muted hover:bg-hover">
              <X size={12} strokeWidth={1.6} aria-hidden />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={draft}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => {
            if (e.target.value.endsWith(",")) commit(e.target.value.slice(0, -1));
            else setDraft(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit(draft);
            } else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
          }}
          onBlur={() => commit(draft)}
          className="h-6 min-w-[100px] flex-1 bg-transparent text-sm outline-none"
          style={{ outline: "none" }}
        />
      </div>
      {remaining.length > 0 && (
        <div className="flex flex-wrap items-center gap-1" aria-label={`${label} suggestions`}>
          <span className="text-xs text-subtle">Suggestions:</span>
          {remaining.map((s) => (
            <button key={s} type="button" onClick={() => onChange([...value, s])} className="mono h-6 rounded-xs border border-dashed border-border-strong px-1.5 text-xs text-muted hover:bg-hover">
              {s}
            </button>
          ))}
        </div>
      )}
    </Field>
  );
}

/** Repeater rows: each row is rendered by `render`; Add appends `blank()`. */
export function Repeater<T>({
  label,
  rows,
  onChange,
  blank,
  render,
  addLabel,
  emptyText,
}: {
  label: string;
  rows: T[];
  onChange: (rows: T[]) => void;
  blank: () => T;
  render: (row: T, update: (patch: Partial<T>) => void, index: number) => ReactNode;
  addLabel: string;
  emptyText: string;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-medium">{label}</legend>
      {rows.length === 0 && <p className="text-sm text-subtle">{emptyText}</p>}
      {rows.map((row, i) => (
        <div key={i} className="flex items-start gap-2 rounded-sm bg-canvas p-3">
          <div className="grid min-w-0 flex-1 gap-3">{render(row, (patch) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r))), i)}</div>
          <Button variant="ghost" icon aria-label={`Remove ${label.toLowerCase()} row ${i + 1}`} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            <Trash2 size={14} strokeWidth={1.6} aria-hidden />
          </Button>
        </div>
      ))}
      <div>
        <Button onClick={() => onChange([...rows, blank()])}>
          <Plus size={14} strokeWidth={1.6} aria-hidden />
          {addLabel}
        </Button>
      </div>
    </fieldset>
  );
}

/** Key-value list for fixtures. Values are stored as strings and parsed (number/bool) by the page on save. */
export function KeyValueList({
  label,
  rows,
  onChange,
  help,
}: {
  label: string;
  rows: { key: string; value: string }[];
  onChange: (rows: { key: string; value: string }[]) => void;
  help?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium">{label}</p>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            aria-label={`${label} name ${i + 1}`}
            value={r.key}
            placeholder="name"
            onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))}
            className={cn(controlClass, "mono w-2/5")}
          />
          <input
            aria-label={`${label} value ${i + 1}`}
            value={r.value}
            placeholder="value"
            onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
            className={cn(controlClass, "mono flex-1")}
          />
          <Button variant="ghost" icon aria-label={`Remove ${label.toLowerCase()} ${i + 1}`} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            <Trash2 size={14} strokeWidth={1.6} aria-hidden />
          </Button>
        </div>
      ))}
      <div>
        <Button onClick={() => onChange([...rows, { key: "", value: "" }])}>
          <Plus size={14} strokeWidth={1.6} aria-hidden />
          Add fact
        </Button>
      </div>
      {help && <p className="text-xs text-subtle">{help}</p>}
    </div>
  );
}
