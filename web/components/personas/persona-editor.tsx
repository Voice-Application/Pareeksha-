"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, fetchAudio, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { INTERRUPT_LABEL, LANGUAGES, LANGUAGE_LABEL, SILENCE_LABEL, VOICES } from "@/lib/format";
import { useUnsavedGuard } from "@/lib/hooks/use-unsaved-guard";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/layout";
import { NumberField, Segmented, SelectField, SliderField, TextAreaField, TextField } from "@/components/ui/field";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { PreviewBar } from "@/components/ui/audio";
import { Strip } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import Link from "next/link";

export type Persona = components["schemas"]["PersonaOut"];
type PersonaCreate = components["schemas"]["PersonaCreate"];

const EMOTIONS = ["neutral", "frustrated", "angry", "confused", "anxious", "polite", "rushed"] as const;
const TTS_MODELS = ["timbre-v3.0", "timbre-v2.5", "timbre-v2.0"];

type Form = {
  name: string;
  language: string;
  code_mix_style: PersonaCreate["code_mix_style"];
  dialect_label: string;
  tts_model: string;
  voice_id: string;
  speed: number;
  emotion: PersonaCreate["emotion"];
  patience_turns: string;
  interruption_level: number;
  silence_habit: PersonaCreate["silence_habit"];
  behaviour_notes: string;
};

const EMPTY: Form = {
  name: "",
  language: "en-IN",
  code_mix_style: "none",
  dialect_label: "",
  tts_model: "timbre-v3.0",
  voice_id: "Shivani",
  speed: 1,
  emotion: "neutral",
  patience_turns: "6",
  interruption_level: 0,
  silence_habit: "normal",
  behaviour_notes: "",
};

function fromPersona(p: Persona): Form {
  return { ...p, patience_turns: String(p.patience_turns) };
}

function toPayload(f: Form): PersonaCreate {
  return { ...f, name: f.name.trim(), dialect_label: f.dialect_label.trim(), behaviour_notes: f.behaviour_notes.trim(), patience_turns: Number(f.patience_turns) };
}

function validate(f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  if (!f.name.trim()) e["pe-name"] = "Enter a name.";
  const n = Number(f.patience_turns);
  if (!Number.isInteger(n) || n < 1 || n > 30) e["pe-patience"] = "Use a whole number from 1 to 30.";
  return e;
}

/** Persona editor. Renders inside a Sheet (list) or on its own page (`/personas/[id]`, deep link). */
export function PersonaEditor({
  persona,
  others,
  mode,
  onDirtyChange,
  onSaved,
  onClose,
}: {
  persona?: Persona;
  others: Persona[];
  mode: "sheet" | "page";
  onDirtyChange?: (dirty: boolean) => void;
  onSaved?: (p: Persona) => void;
  onClose?: () => void;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const initial = useMemo(() => (persona ? fromPersona(persona) : EMPTY), [persona]);
  const [form, setForm] = useState<Form>(initial);
  const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [refused, setRefused] = useState<{ message: string; runs: { id: string; name?: string }[] } | null>(null);
  const summary = useRef<HTMLDivElement>(null);

  const dirty = JSON.stringify(form) !== baseline;
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
  const guard = useUnsavedGuard(dirty && mode === "page");

  const errors = validate(form);
  const patch = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));

  const sameVoice = others.find((o) => o.id !== persona?.id && o.language === form.language && o.voice_id === form.voice_id);

  const save = useMutation({
    mutationFn: (payload: PersonaCreate) =>
      persona ? call(api.PATCH("/api/v1/personas/{persona_id}", { params: { path: { persona_id: persona.id } }, body: payload })) : call(api.POST("/api/v1/personas", { body: payload })),
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setServerError(null);
    const first = Object.keys(errors)[0];
    if (first) {
      requestAnimationFrame(() => {
        summary.current?.focus();
        document.getElementById(first)?.focus();
      });
      return;
    }
    try {
      const saved = await save.mutateAsync(toPayload(form));
      guard.release();
      void qc.invalidateQueries({ queryKey: ["personas"] });
      qc.setQueryData(["persona", saved.id], saved);
      toast(persona ? `Saved ${saved.name}.` : `Created ${saved.name}.`);
      const f = fromPersona(saved);
      setForm(f);
      setBaseline(JSON.stringify(f));
      onSaved?.(saved);
      if (mode === "page" && !persona) router.replace(`/personas/${saved.id}`);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.userMessage() : "The request failed.");
    }
  }

  const del = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/personas/{persona_id}", { params: { path: { persona_id: persona!.id } } })),
    onSuccess: () => {
      setConfirmDelete(false);
      guard.release();
      toast(`Deleted ${persona!.name}.`);
      void qc.invalidateQueries({ queryKey: ["personas"] });
      if (mode === "page") router.push("/personas");
      else onClose?.();
    },
    onError: (e) => {
      setConfirmDelete(false);
      if (e instanceof ApiError && e.status === 409) setRefused({ message: e.userMessage(), runs: Array.isArray(e.details.runs) ? (e.details.runs as { id: string; name?: string }[]) : [] });
      else toast(`Could not delete: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => del.mutate() } });
    },
  });

  const errCount = Object.keys(errors).length;
  const previewKey = persona ? JSON.stringify(persona) : "unsaved";

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6">
      {submitted && errCount > 0 && (
        <div ref={summary} tabIndex={-1} role="alert" className="border-l-2 border-fail bg-fail-tint px-3 py-2 text-sm">
          <p className="font-medium text-fail-fg">Fix {errCount} {errCount === 1 ? "field" : "fields"} before saving.</p>
          <ul className="mt-1 list-disc pl-5">
            {Object.entries(errors).map(([id, msg]) => (
              <li key={id}>{msg}</li>
            ))}
          </ul>
        </div>
      )}
      {serverError && <Strip tone="error">Could not save. {serverError}</Strip>}

      <fieldset className="grid gap-4">
        <legend className="eyebrow mb-2 flex items-center gap-2">
          Who {persona?.is_seed && <Chip>seed</Chip>}
        </legend>
        <TextField id="pe-name" label="Name" required value={form.name} onChange={(e) => patch({ name: e.target.value })} error={submitted ? errors["pe-name"] : undefined} />
        <SelectField label="Language" value={form.language} onChange={(e) => patch({ language: e.target.value })}>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {LANGUAGE_LABEL[l]} ({l})
            </option>
          ))}
        </SelectField>
        <Segmented label="Code-mix style" value={form.code_mix_style} onChange={(v) => patch({ code_mix_style: v })} options={[{ value: "none", label: "None" }, { value: "light", label: "Light" }, { value: "heavy", label: "Heavy" }]} />
        <TextField label="Dialect label" value={form.dialect_label} onChange={(e) => patch({ dialect_label: e.target.value })} help="Descriptive only. We do not claim the voice is that dialect." />
      </fieldset>

      <fieldset className="grid gap-4">
        <legend className="eyebrow mb-2">Voice</legend>
        <SelectField label="TTS model" value={form.tts_model} onChange={(e) => patch({ tts_model: e.target.value })}>
          {TTS_MODELS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </SelectField>
        <SelectField label="Voice" value={form.voice_id} onChange={(e) => patch({ voice_id: e.target.value })} help="Voices are Gnani stock voices. Do not use a real person's voice.">
          {[...new Set([...VOICES, form.voice_id])].map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </SelectField>
        {sameVoice && (
          <p className="flex items-center gap-1 text-xs text-warn-fg">
            <TriangleAlert size={14} strokeWidth={1.6} aria-hidden />
            Same voice as {sameVoice.name}, {sameVoice.language}
          </p>
        )}
        <SliderField label="Speed" min={0.8} max={1.3} step={0.05} value={form.speed} onChange={(speed) => patch({ speed: Math.round(speed * 100) / 100 })} format={(v) => `${v.toFixed(2)}x`} />
        <SelectField label="Emotion" value={form.emotion} onChange={(e) => patch({ emotion: e.target.value as Form["emotion"] })}>
          {EMOTIONS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </SelectField>
      </fieldset>

      <fieldset className="grid gap-4">
        <legend className="eyebrow mb-2">Behaviour</legend>
        <NumberField id="pe-patience" label="Patience (turns)" min={1} max={30} value={form.patience_turns} onChange={(e) => patch({ patience_turns: e.target.value })} error={submitted ? errors["pe-patience"] : undefined} fieldClassName="max-w-[160px]" help="Turns before the caller gives up." />
        <Segmented
          label="Interruption level"
          value={form.interruption_level}
          onChange={(v) => patch({ interruption_level: v })}
          options={INTERRUPT_LABEL.map((label, i) => ({ value: i, label: `${i}`, hint: label }))}
          help={`${form.interruption_level}: ${INTERRUPT_LABEL[form.interruption_level].toLowerCase()} interrupts the agent.`}
        />
        <SelectField label="Silence habit" value={form.silence_habit} onChange={(e) => patch({ silence_habit: e.target.value as Form["silence_habit"] })}>
          {Object.entries(SILENCE_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </SelectField>
        <TextAreaField label="Behaviour notes" rows={4} value={form.behaviour_notes} onChange={(e) => patch({ behaviour_notes: e.target.value })} />
      </fieldset>

      <div className={mode === "sheet" ? "sticky bottom-0 -mx-4 -mb-4 grid gap-3 border-t border-border bg-surface p-4" : "sticky bottom-0 grid gap-3 border-t border-border bg-canvas py-3"}>
        <PreviewBar
          label="Play sample line"
          load={() => fetchAudio(`/api/v1/personas/${persona!.id}/preview`)}
          cacheKey={previewKey}
          disabled={!persona || dirty}
          disabledReason={!persona ? "Save the persona to preview its voice." : "Save your changes to preview them. The preview uses the saved settings."}
          note="Uses Gnani TTS credits. Repeated lines are cached by the server."
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" loading={save.isPending}>
            {persona ? "Save changes" : "Create persona"}
          </Button>
          {mode === "page" ? (
            <Link href="/personas" className="inline-flex h-8 items-center px-3 text-sm text-muted hover:text-fg">
              Cancel
            </Link>
          ) : (
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          )}
          {persona && (
            <Button variant="destructive" className="ml-auto" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} strokeWidth={1.6} aria-hidden />
              Delete
            </Button>
          )}
        </div>
      </div>

      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete ${persona?.name ?? "persona"}?`} body="This removes the persona. Personas used by a run cannot be deleted." confirmLabel="Delete persona" busy={del.isPending} onConfirm={() => del.mutate()} />
      <Dialog open={!!refused} onClose={() => setRefused(null)} title={`${persona?.name ?? "Persona"} is in use`} footer={<Button onClick={() => setRefused(null)}>Close</Button>}>
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
      {guard.dialog}
    </form>
  );
}
