"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { LANGUAGE_LABEL, LANGUAGES } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { FileDropzone } from "@/components/ui/audio";
import { SelectField, Switch } from "@/components/ui/field";
import { Strip } from "@/components/ui/states";

/** Multipart upload to POST /audits through the BFF proxy; on 202 the call page opens in `transcribing`. */
export function AuditUpload() {
  const router = useRouter();
  const agents = useQuery({ queryKey: ["agents", "options"], queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 100 } } })) });
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [agentId, setAgentId] = useState("");
  const [langs, setLangs] = useState<string[]>(["kn-IN"]);
  const [stereo, setStereo] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const items = (agents.data?.items ?? []).filter((a) => !a.archived);
  const missing = [!file && "Choose a recording", !agentId && "Choose an agent", langs.length === 0 && "Choose a language", !consent && "Confirm you may process this recording"].filter(Boolean) as string[];

  async function submit() {
    if (missing.length || !file) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.set("file", file);
    fd.set("agent_id", agentId);
    fd.set("language", langs.join(","));
    fd.set("stereo_channels_are_speakers", String(stereo));
    try {
      const res = await fetch("/api/proxy/api/v1/audits", { method: "POST", body: fd });
      const body = await res.json().catch(() => null);
      if (res.status === 202) {
        router.push(`/calls/${(body as { call_id?: string; id?: string }).call_id ?? (body as { id: string }).id}`);
        return;
      }
      const e = (body as { error?: { code?: string; message?: string } } | null)?.error;
      setError(
        res.status === 501 ? "Audits cannot be created in this build yet (the API route is not implemented)."
        : res.status === 413 ? "The file is larger than the 10 MB limit."
        : res.status === 403 ? "Your key cannot upload audits (needs audits:write)."
        : res.status === 422 ? "We could not read this audio. Use a WAV or MP3."
        : (e?.message ?? "The upload failed."),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.userMessage() : "The API did not respond. Your file is still selected; try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow={<Link href="/audits" className="underline-offset-2 hover:underline">Audits</Link>} title="Upload a recording" description="The recording is transcribed with speaker separation, scored with the same rubric as simulated calls, and listed under Audits." />
      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,680px)_380px]">
        <Panel title="Recording">
          <div className="flex flex-col gap-5">
            {error && <Strip tone="error">{error}</Strip>}
            <FileDropzone file={file} onFile={setFile} error={fileError} onError={setFileError} />
            <SelectField label="Agent" help="Used as rubric context." value={agentId} onChange={(e) => setAgentId(e.target.value)}>
              <option value="">Choose an agent</option>
              {items.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </SelectField>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-medium">Language</legend>
              <div className="flex flex-wrap gap-4">
                {LANGUAGES.map((l) => (
                  <label key={l} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={langs.includes(l)} onChange={() => setLangs((c) => (c.includes(l) ? c.filter((x) => x !== l) : [...c, l]))} />
                    {LANGUAGE_LABEL[l]} <span className="mono text-xs text-muted">{l}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-subtle">Code-mixed calls: pick two.</p>
            </fieldset>
            <Switch label="Stereo channels are speakers" checked={stereo} onChange={setStereo} help="Turn on if the agent and caller were recorded on separate channels. Skips diarisation." />
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              I have the right to process this recording and it contains no data I am not allowed to store.
            </label>
            <div className="flex items-center gap-3">
              <Button variant="primary" loading={busy} disabled={missing.length > 0} onClick={() => void submit()}>
                Upload and audit
              </Button>
              {missing.length > 0 && <span className="text-xs text-subtle">{missing[0]}.</span>}
            </div>
          </div>
        </Panel>
        <Panel title="What happens next">
          <ol className="list-decimal space-y-2 pl-5 text-sm text-muted">
            <li>Transcribe with speaker separation.</li>
            <li>Find which speaker is the agent. You can swap them on the call page.</li>
            <li>Run the same checks and the judge.</li>
            <li>Score the call and flag it for review when needed.</li>
          </ol>
          <p className="mt-3 text-xs text-subtle">About 1-2 minutes for a short call.</p>
        </Panel>
      </div>
    </>
  );
}
