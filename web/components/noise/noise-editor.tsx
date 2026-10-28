"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, fetchAudio, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { useUnsavedGuard } from "@/lib/hooks/use-unsaved-guard";
import { Button } from "@/components/ui/button";
import { Segmented, SelectField, SliderField, Switch, TextField } from "@/components/ui/field";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { FileDropzone, PreviewBar } from "@/components/ui/audio";
import { Strip } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { useAudioPreview } from "@/lib/hooks/use-audio-preview";

export type NoiseProfile = components["schemas"]["NoiseProfileOut"];
type NoiseCreate = components["schemas"]["NoiseProfileCreate"];

export const BACKGROUNDS = ["office_babble", "street_traffic", "market_crowd", "bus_interior", "auto_rickshaw"];

type Form = {
  name: string;
  description: string;
  sample_rate: 8000 | 16000;
  codec: NoiseCreate["codec"];
  pstn_bandpass: boolean;
  background: string;
  snr_db: number;
  packet_loss_pct: number;
  clipping: boolean;
};

const EMPTY: Form = { name: "", description: "", sample_rate: 8000, codec: "alaw", pstn_bandpass: true, background: "", snr_db: 15, packet_loss_pct: 0, clipping: false };

function fromProfile(p: NoiseProfile): Form {
  return {
    name: p.name,
    description: p.description,
    sample_rate: p.sample_rate,
    codec: p.codec,
    pstn_bandpass: p.pstn_bandpass,
    background: p.background_category ?? "",
    snr_db: p.snr_db ?? 15,
    packet_loss_pct: p.packet_loss_pct,
    clipping: p.clipping,
  };
}

function toPayload(f: Form): NoiseCreate {
  return {
    name: f.name.trim(),
    description: f.description.trim(),
    sample_rate: f.sample_rate,
    codec: f.codec,
    pstn_bandpass: f.pstn_bandpass,
    background_category: f.background || null,
    snr_db: f.background ? f.snr_db : null,
    packet_loss_pct: f.packet_loss_pct,
    clipping: f.clipping,
  };
}

function validate(f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  if (!f.name.trim()) e["np-name"] = "Enter a name.";
  else if (!/^[a-z0-9][a-z0-9_]*$/.test(f.name.trim())) e["np-name"] = "Use lowercase letters, digits and underscores, for example pstn_street_10db.";
  return e;
}

/** A/B playback of an uploaded clip: original, then the processed version. */
function AbPlayer({ original, load, cacheKey }: { original: File; load: () => Promise<Blob>; cacheKey: string }) {
  const orig = useAudioPreview(async () => original, `${original.name}:${original.size}:${original.lastModified}`);
  const proc = useAudioPreview(load, cacheKey);
  return (
    <div className="grid gap-2">
      <div className="inline-flex gap-2">
        {[
          { label: "Original", p: orig },
          { label: "Processed", p: proc },
        ].map(({ label, p }) => (
          <Button key={label} onClick={() => void p.toggle()}>
            {p.state === "loading" ? <span className="spinner" aria-hidden /> : p.state === "playing" ? <Pause size={14} strokeWidth={1.6} aria-hidden /> : <Play size={14} strokeWidth={1.6} aria-hidden />}
            {label}
          </Button>
        ))}
      </div>
      {proc.state === "error" && proc.error && (
        <Strip tone="error" onRetry={() => void proc.toggle()}>
          Could not process the clip: {proc.error}
        </Strip>
      )}
    </div>
  );
}

export function NoiseEditor({
  profile,
  mode,
  onDirtyChange,
  onSaved,
  onClose,
}: {
  profile?: NoiseProfile;
  mode: "sheet" | "page";
  onDirtyChange?: (dirty: boolean) => void;
  onSaved?: (p: NoiseProfile) => void;
  onClose?: () => void;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const initial = useMemo(() => (profile ? fromProfile(profile) : EMPTY), [profile]);
  const [form, setForm] = useState<Form>(initial);
  const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [refused, setRefused] = useState<{ message: string; runs: { id: string; name?: string }[] } | null>(null);
  const [previewMode, setPreviewMode] = useState<"sample" | "mine">("sample");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const summary = useRef<HTMLDivElement>(null);

  const dirty = JSON.stringify(form) !== baseline;
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
  const guard = useUnsavedGuard(dirty && mode === "page");
  const errors = validate(form);
  const patch = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));

  const save = useMutation({
    mutationFn: (payload: NoiseCreate) =>
      profile ? call(api.PATCH("/api/v1/noise-profiles/{noise_profile_id}", { params: { path: { noise_profile_id: profile.id } }, body: payload })) : call(api.POST("/api/v1/noise-profiles", { body: payload })),
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
      void qc.invalidateQueries({ queryKey: ["noise-profiles"] });
      qc.setQueryData(["noise-profile", saved.id], saved);
      toast(profile ? `Saved ${saved.name}.` : `Created ${saved.name}.`);
      const f = fromProfile(saved);
      setForm(f);
      setBaseline(JSON.stringify(f));
      onSaved?.(saved);
      if (mode === "page" && !profile) router.replace(`/noise-profiles/${saved.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setServerError("A noise profile with this name already exists.");
      else setServerError(err instanceof ApiError ? err.userMessage() : "The request failed.");
    }
  }

  const del = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/noise-profiles/{noise_profile_id}", { params: { path: { noise_profile_id: profile!.id } } })),
    onSuccess: () => {
      setConfirmDelete(false);
      guard.release();
      toast(`Deleted ${profile!.name}.`);
      void qc.invalidateQueries({ queryKey: ["noise-profiles"] });
      if (mode === "page") router.push("/noise-profiles");
      else onClose?.();
    },
    onError: (e) => {
      setConfirmDelete(false);
      if (e instanceof ApiError && e.status === 409) setRefused({ message: e.userMessage(), runs: Array.isArray(e.details.runs) ? (e.details.runs as { id: string; name?: string }[]) : [] });
      else toast(`Could not delete: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error", action: { label: "Retry", run: () => del.mutate() } });
    },
  });

  const loadPreview = async () => {
    const path = `/api/v1/noise-profiles/${profile!.id}/preview`;
    if (previewMode === "mine" && file) {
      const body = new FormData();
      body.append("file", file);
      return fetchAudio(path, { body });
    }
    return fetchAudio(path);
  };
  const previewKey = `${profile ? JSON.stringify(profile) : "unsaved"}|${previewMode}|${previewMode === "mine" ? `${file?.name}:${file?.size}` : ""}`;
  const errCount = Object.keys(errors).length;
  const noBackground = !form.background;
  const unrealistic = form.sample_rate === 16000 && form.pstn_bandpass;

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

      <div className="grid gap-4">
        <TextField id="np-name" label="Name" required className="mono" value={form.name} onChange={(e) => patch({ name: e.target.value })} error={submitted ? errors["np-name"] : undefined} help="Lowercase with underscores. Must be unique." />
        <TextField label="Represents" value={form.description} onChange={(e) => patch({ description: e.target.value })} help="Optional. The situation this line stands for, such as a vegetable market." />
        <Segmented label="Sample rate" value={form.sample_rate} onChange={(v) => patch({ sample_rate: v })} options={[{ value: 8000, label: "8 kHz" }, { value: 16000, label: "16 kHz" }]} />
        <Segmented label="Codec" value={form.codec} onChange={(v) => patch({ codec: v })} options={[{ value: "none", label: "None" }, { value: "mulaw", label: "mu-law" }, { value: "alaw", label: "A-law" }]} help="India's landline network uses A-law." />
        <Switch label="PSTN bandpass" checked={form.pstn_bandpass} onChange={(v) => patch({ pstn_bandpass: v })} />
        {unrealistic && (
          <p className="flex items-start gap-1 text-xs text-warn-fg">
            <TriangleAlert size={14} strokeWidth={1.6} className="mt-px shrink-0" aria-hidden />
            Phone lines are 8 kHz. This profile will sound unrealistic.
          </p>
        )}
        <SelectField label="Background" value={form.background} onChange={(e) => patch({ background: e.target.value })}>
          <option value="">None</option>
          {[...new Set([...BACKGROUNDS, form.background].filter(Boolean))].map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </SelectField>
        <SliderField label="SNR" min={0} max={30} step={1} value={form.snr_db} disabled={noBackground} onChange={(snr_db) => patch({ snr_db })} format={(v) => (noBackground ? "n/a" : `${v} dB`)} help={noBackground ? "Choose a background to set the signal-to-noise ratio." : "Lower is harsher. 0 dB means the noise is as loud as the voice."} />
        <SliderField label="Packet loss" min={0} max={10} step={0.5} value={form.packet_loss_pct} onChange={(packet_loss_pct) => patch({ packet_loss_pct })} format={(v) => `${v}%`} />
        <Switch label="Clipping" checked={form.clipping} onChange={(v) => patch({ clipping: v })} help="Distortion from a loud microphone." />
      </div>

      <div className={mode === "sheet" ? "sticky bottom-0 -mx-4 -mb-4 grid gap-3 border-t border-border bg-surface p-4" : "sticky bottom-0 grid gap-3 border-t border-border bg-canvas py-3"}>
        <Segmented label="Preview" value={previewMode} onChange={setPreviewMode} options={[{ value: "sample", label: "Sample clip" }, { value: "mine", label: "My clip" }]} />
        {previewMode === "mine" && <FileDropzone file={file} onFile={setFile} error={fileError} onError={setFileError} />}
        {previewMode === "mine" && file && profile && !dirty ? (
          <AbPlayer original={file} load={loadPreview} cacheKey={previewKey} />
        ) : (
          <PreviewBar
            label={previewMode === "sample" ? "Play sample clip" : "Play processed clip"}
            load={loadPreview}
            cacheKey={previewKey}
            disabled={!profile || dirty || (previewMode === "mine" && !file)}
            disabledReason={!profile ? "Save the profile to preview it." : dirty ? "Save your changes to preview them. The preview uses the saved settings." : "Choose a clip to process."}
            note={previewMode === "sample" ? "The default sample, degraded with the saved settings." : "Your clip, degraded with the saved settings."}
          />
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" loading={save.isPending}>
            {profile ? "Save changes" : "Create profile"}
          </Button>
          {mode === "page" ? (
            <Link href="/noise-profiles" className="inline-flex h-8 items-center px-3 text-sm text-muted hover:text-fg">
              Cancel
            </Link>
          ) : (
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          )}
          {profile && (
            <Button variant="destructive" className="ml-auto" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} strokeWidth={1.6} aria-hidden />
              Delete
            </Button>
          )}
        </div>
      </div>

      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete ${profile?.name ?? "profile"}?`} body="This removes the noise profile. Profiles used by a run cannot be deleted." confirmLabel="Delete profile" busy={del.isPending} onConfirm={() => del.mutate()} />
      <Dialog open={!!refused} onClose={() => setRefused(null)} title={`${profile?.name ?? "Profile"} is in use`} footer={<Button onClick={() => setRefused(null)}>Close</Button>}>
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
