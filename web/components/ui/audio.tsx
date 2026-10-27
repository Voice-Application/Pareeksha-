"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import { FileAudio, Pause, Play, X } from "lucide-react";
import { Button } from "./button";
import { useAudioPreview } from "@/lib/hooks/use-audio-preview";
import { Strip } from "./states";
import { cn } from "@/lib/utils";
import { useLatest } from "@/lib/hooks/use-latest";

/** 28px play button for table rows. Loads the clip on first press. */
export function RowPlayButton({ label, load, cacheKey, onError }: { label: string; load: () => Promise<Blob>; cacheKey: string; onError?: (message: string) => void }) {
  const p = useAudioPreview(load, cacheKey);
  const onErrorRef = useLatest(onError);
  useEffect(() => {
    if (p.state === "error" && p.error) onErrorRef.current?.(p.error);
  }, [p.state, p.error, onErrorRef]);
  return (
    <button
      type="button"
      onClick={() => void p.toggle()}
      aria-label={p.state === "playing" ? `Pause ${label}` : `Play ${label}`}
      aria-busy={p.state === "loading"}
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border-strong text-accent-fg hover:bg-hover",
        p.state === "playing" && "bg-accent-tint",
      )}
      style={{ borderRadius: "var(--radius-pill)" }}
    >
      {p.state === "loading" ? <span className="spinner" aria-hidden /> : p.state === "playing" ? <Pause size={12} strokeWidth={1.6} aria-hidden /> : <Play size={12} strokeWidth={1.6} aria-hidden />}
    </button>
  );
}

/** PreviewBar: play button, duration, note and inline failure with Retry. The form stays editable. */
export function PreviewBar({
  label,
  load,
  cacheKey,
  disabled,
  disabledReason,
  note,
  extra,
}: {
  label: string;
  load: () => Promise<Blob>;
  cacheKey: string;
  disabled?: boolean;
  disabledReason?: string;
  note?: string;
  extra?: React.ReactNode;
}) {
  const p = useAudioPreview(load, cacheKey);
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" disabled={disabled} onClick={() => void p.toggle()} aria-describedby="preview-note">
          {p.state === "loading" ? <span className="spinner" aria-hidden /> : p.state === "playing" ? <Pause size={14} strokeWidth={1.6} aria-hidden /> : <Play size={14} strokeWidth={1.6} aria-hidden />}
          {p.state === "playing" ? "Pause" : label}
        </Button>
        {p.state === "loading" && <span className="skeleton h-3 w-24" aria-hidden />}
        {p.duration !== null && p.state !== "loading" && <span className="mono text-sm text-muted">{p.duration.toFixed(1)} s</span>}
        {extra}
      </div>
      <p id="preview-note" className="text-xs text-subtle">
        {disabled && disabledReason ? disabledReason : note}
      </p>
      {p.state === "error" && p.error && (
        <Strip tone="error" onRetry={() => void p.toggle()}>
          Could not synthesise: {p.error}
        </Strip>
      )}
    </div>
  );
}

export const MAX_UPLOAD = 10 * 1024 * 1024;

/** Dashed drop area. Accepts a WAV or MP3 up to 10 MB and shows name, size and a remove button. */
export function FileDropzone({ file, onFile, error, onError }: { file: File | null; onFile: (f: File | null) => void; error?: string | null; onError: (m: string | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function take(f: File | undefined) {
    if (!f) return;
    const ok = /\.(wav|mp3)$/i.test(f.name) || /^audio\/(wav|x-wav|wave|mpeg|mp3)$/.test(f.type);
    if (!ok || f.size > MAX_UPLOAD) {
      onFile(null);
      onError("Use a WAV or MP3 under 10 MB.");
      return;
    }
    onError(null);
    onFile(f);
  }

  return (
    <div className="grid gap-1">
      <div
        onDragOver={(e: DragEvent) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e: DragEvent) => {
          e.preventDefault();
          setOver(false);
          take(e.dataTransfer.files[0]);
        }}
        className={cn("flex min-h-[72px] items-center justify-between gap-3 rounded-md border border-dashed border-border-strong p-3", over && "bg-accent-tint")}
      >
        {file ? (
          <>
            <span className="flex min-w-0 items-center gap-2 text-sm">
              <FileAudio size={16} strokeWidth={1.6} className="shrink-0 text-muted" aria-hidden />
              <span className="mono truncate">{file.name}</span>
              <span className="mono shrink-0 text-xs text-subtle">{(file.size / 1024).toFixed(0)} KB</span>
            </span>
            <Button
              variant="ghost"
              icon
              aria-label="Remove file"
              onClick={() => {
                onFile(null);
                if (input.current) input.current.value = "";
              }}
            >
              <X size={14} strokeWidth={1.6} aria-hidden />
            </Button>
          </>
        ) : (
          <>
            <p className="text-sm text-muted">Drop a WAV or MP3 here, up to 10 MB.</p>
            <Button onClick={() => input.current?.click()}>Choose file</Button>
          </>
        )}
        <input ref={input} type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" className="sr-only" tabIndex={-1} aria-label="Audio file" onChange={(e) => take(e.target.files?.[0])} />
      </div>
      {error && (
        <p role="alert" className="text-xs text-fail-fg">
          {error}
        </p>
      )}
    </div>
  );
}
