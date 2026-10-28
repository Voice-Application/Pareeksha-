"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { useAgentOptions } from "@/lib/hooks/use-agents";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/layout";
import { Dialog, ConfirmDialog, Sheet } from "@/components/ui/overlay";
import { NumberField, SelectField, SliderField, TagInput, TextAreaField, TextField } from "@/components/ui/field";
import { Skeleton, Strip } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";

type Draft = components["schemas"]["ScenarioCreate"];
type Mix = { happy_path: number; edge_case: number; adversarial: number };
const MIX_KEYS: { key: keyof Mix; label: string }[] = [
  { key: "happy_path", label: "Happy path" },
  { key: "edge_case", label: "Edge case" },
  { key: "adversarial", label: "Adversarial" },
];

/** Keep the three sliders summing to `count`: the other two share what is left in their current ratio. */
function rebalance(mix: Mix, key: keyof Mix, value: number, count: number): Mix {
  const v = Math.max(0, Math.min(count, value));
  const others = MIX_KEYS.map((k) => k.key).filter((k) => k !== key);
  const rest = count - v;
  const currentOthers = others.reduce((s, k) => s + mix[k], 0);
  const first = currentOthers === 0 ? Math.floor(rest / 2) : Math.round((rest * mix[others[0]]) / currentOthers);
  return { ...mix, [key]: v, [others[0]]: first, [others[1]]: rest - first } as Mix;
}

function scaleMix(mix: Mix, count: number): Mix {
  const total = mix.happy_path + mix.edge_case + mix.adversarial || 1;
  const h = Math.round((mix.happy_path / total) * count);
  const e = Math.min(count - h, Math.round((mix.edge_case / total) * count));
  return { happy_path: h, edge_case: e, adversarial: count - h - e };
}

export function GenerateSheet({ open, onClose, defaultAgentId }: { open: boolean; onClose: () => void; defaultAgentId?: string }) {
  const agents = useAgentOptions();
  const qc = useQueryClient();
  const { toast } = useToast();

  const [phase, setPhase] = useState<"setup" | "generating" | "review">("setup");
  const [pickedAgent, setPickedAgent] = useState("");
  const [count, setCount] = useState(10);
  const [mix, setMix] = useState<Mix>({ happy_path: 4, edge_case: 3, adversarial: 3 });
  const [draftId, setDraftId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [discardReason, setDiscardReason] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [editBuf, setEditBuf] = useState<Draft | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);

  // The picked agent, else the one filtered on the list, else the first available.
  const agentId = pickedAgent || defaultAgentId || agents.data?.[0]?.id || "";

  function reset() {
    setPhase("setup");
    setDraftId(null);
    setDrafts([]);
    setSelected(new Set());
    setDiscardReason(null);
  }

  const start = useMutation({
    mutationFn: () => call(api.POST("/api/v1/agents/{agent_id}/scenarios:generate", { params: { path: { agent_id: agentId } }, body: { count, mix } })),
    onSuccess: (r) => {
      setDraftId(r.draft_id);
      setPhase("generating");
    },
  });

  const poll = useQuery({
    queryKey: ["scenario-draft", draftId],
    queryFn: () => call(api.GET("/api/v1/scenario-drafts/{draft_id}", { params: { path: { draft_id: draftId! } } })),
    enabled: phase === "generating" && !!draftId,
    refetchInterval: (q) => (q.state.data?.status === "pending" || !q.state.data ? 1500 : false),
    retry: 2,
  });

  // When the draft turns ready, move to review once (adjusting state while rendering, not in an effect).
  const [reviewedDraft, setReviewedDraft] = useState<string | null>(null);
  const ready = phase === "generating" && poll.data?.status === "ready" ? poll.data : null;
  if (ready && reviewedDraft !== ready.id) {
    const rows = ready.drafts ?? [];
    setReviewedDraft(ready.id);
    setDrafts(rows);
    setSelected(new Set(rows.map((_, i) => i)));
    setDiscardReason(ready.error ?? null);
    setPhase("review");
  }

  const failedMessage = poll.data?.status === "failed" ? (poll.data.error ?? "The generator could not produce scenarios.") : null;

  const save = useMutation({
    mutationFn: () => call(api.POST("/api/v1/scenarios:bulk", { body: { scenarios: drafts.filter((_, i) => selected.has(i)), source: "generated" } })),
    onSuccess: (r) => {
      toast(`Saved ${r.items.length} ${r.items.length === 1 ? "scenario" : "scenarios"}.`);
      void qc.invalidateQueries({ queryKey: ["scenarios"] });
      reset();
      onClose();
    },
  });

  function requestClose() {
    if (phase === "review" && drafts.length > 0 && !save.isSuccess) setConfirmClose(true);
    else {
      if (phase === "generating") reset();
      onClose();
    }
  }

  const err = (m: { error: unknown }) => (m.error instanceof ApiError ? m.error.userMessage() : "The request failed.");

  return (
    <>
      <Sheet
        open={open}
        onClose={requestClose}
        title="Generate scenarios with AI"
        wide
        footer={
          phase === "review" ? (
            <div className="flex items-center justify-between gap-2">
              <Button variant="ghost" onClick={reset}>
                Start over
              </Button>
              <Button variant="primary" disabled={selected.size === 0} loading={save.isPending} onClick={() => save.mutate()}>
                Save {selected.size} selected
              </Button>
            </div>
          ) : phase === "setup" ? (
            <div className="flex justify-end">
              <Button variant="primary" disabled={!agentId} loading={start.isPending} onClick={() => start.mutate()}>
                Generate
              </Button>
            </div>
          ) : undefined
        }
      >
        {phase === "setup" && (
          <div className="grid gap-4">
            <p className="text-sm text-muted">Gemini drafts scenarios from the agent&apos;s description. Nothing is saved until you review the drafts and save the ones you want.</p>
            <SelectField label="Agent" value={agentId} onChange={(e) => setPickedAgent(e.target.value)}>
              {agents.isPending && <option value="">Loading agents</option>}
              {agents.data?.length === 0 && <option value="">No agents yet</option>}
              {agents.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </SelectField>
            <NumberField
              label="How many"
              min={1}
              max={20}
              value={count}
              onChange={(e) => {
                const n = Math.max(1, Math.min(20, Number(e.target.value) || 1));
                setCount(n);
                setMix((m) => scaleMix(m, n));
              }}
              fieldClassName="max-w-[160px]"
              help="1 to 20."
            />
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-medium">
                Mix <span className="mono text-xs font-normal text-subtle">always adds up to {count}</span>
              </legend>
              {MIX_KEYS.map((k) => (
                <SliderField key={k.key} label={k.label} min={0} max={count} step={1} value={mix[k.key]} onChange={(v) => setMix((m) => rebalance(m, k.key, v, count))} />
              ))}
            </fieldset>
            {start.isError && <Strip tone="error">Could not start generation. {err(start)}</Strip>}
          </div>
        )}

        {phase === "generating" && !failedMessage && (
          <div className="grid gap-3" role="status" aria-live="polite">
            <p className="text-sm">
              Generating <span className="mono">{count}</span> scenarios. This takes a short while.
            </p>
            {Array.from({ length: Math.min(count, 4) }, (_, i) => (
              <div key={i} className="rounded-md border border-border p-3">
                <Skeleton className="mb-2 h-4 w-1/2" />
                <Skeleton className="h-3 w-full" />
              </div>
            ))}
            {poll.isError && <Strip tone="error" onRetry={() => void poll.refetch()}>Could not check progress. {err(poll)}</Strip>}
            <div>
              <Button variant="ghost" onClick={reset}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {phase === "generating" && failedMessage && (
          <div className="grid gap-3">
            <Strip tone="error">Generation failed. {failedMessage}</Strip>
            <div>
              <Button variant="primary" onClick={() => start.mutate()} loading={start.isPending}>
                Try again
              </Button>
              <Button variant="ghost" className="ml-2" onClick={reset}>
                Change settings
              </Button>
            </div>
          </div>
        )}

        {phase === "review" && (
          <div className="grid gap-3">
            {drafts.length < count && (
              <Strip tone="warn">
                <p>
                  <span className="mono">{drafts.length}</span> of <span className="mono">{count}</span> drafts passed validation. <span className="mono">{count - drafts.length}</span> were discarded.
                </p>
                {discardReason && (
                  <details className="mt-1 text-xs">
                    <summary className="cursor-pointer">Reasons</summary>
                    <p className="mt-1">{discardReason}</p>
                  </details>
                )}
              </Strip>
            )}
            {drafts.length === 0 && <p className="text-sm text-muted">No valid drafts came back. Start over to try again.</p>}
            {save.isError && <Strip tone="error" onRetry={() => save.mutate()}>Could not save. {err(save)}</Strip>}
            <ul className="grid gap-3">
              {drafts.map((d, i) => (
                <li key={i} className="rounded-md border border-border bg-surface p-3">
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      aria-label={`Keep draft: ${d.title}`}
                      checked={selected.has(i)}
                      onChange={(e) =>
                        setSelected((s) => {
                          const n = new Set(s);
                          if (e.target.checked) n.add(i);
                          else n.delete(i);
                          return n;
                        })
                      }
                      className="mt-1 h-4 w-4"
                      style={{ accentColor: "var(--accent)" }}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{d.title}</p>
                      <p className="mt-1 text-sm text-muted">{d.caller_goal}</p>
                      <p className="mt-1 text-sm">
                        <span className="text-subtle">Success: </span>
                        {d.success_criteria}
                      </p>
                      {d.tags && d.tags.length > 0 && (
                        <p className="mt-2 flex flex-wrap gap-1">
                          {d.tags.map((t) => (
                            <Chip key={t} mono>
                              {t}
                            </Chip>
                          ))}
                        </p>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditing(i);
                        setEditBuf(d);
                      }}
                      aria-label={`Edit draft: ${d.title}`}
                    >
                      <Pencil size={14} strokeWidth={1.6} aria-hidden />
                      Edit
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Sheet>

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title="Edit draft"
        footer={
          <>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
            <Button
              variant="primary"
              onClick={() => {
                if (editing !== null && editBuf) setDrafts((ds) => ds.map((d, i) => (i === editing ? editBuf : d)));
                setEditing(null);
              }}
            >
              Apply
            </Button>
          </>
        }
      >
        {editBuf && (
          <div className="grid gap-3">
            <TextField label="Title" value={editBuf.title} onChange={(e) => setEditBuf({ ...editBuf, title: e.target.value })} />
            <TextAreaField label="Caller goal" rows={3} value={editBuf.caller_goal} onChange={(e) => setEditBuf({ ...editBuf, caller_goal: e.target.value })} />
            <TextAreaField label="Success criteria" rows={3} value={editBuf.success_criteria} onChange={(e) => setEditBuf({ ...editBuf, success_criteria: e.target.value })} />
            <TagInput label="Tags" mono value={editBuf.tags ?? []} onChange={(tags) => setEditBuf({ ...editBuf, tags })} />
          </div>
        )}
      </Dialog>

      <ConfirmDialog
        open={confirmClose}
        onClose={() => setConfirmClose(false)}
        title="Discard unsaved drafts?"
        body="The drafts have not been saved. Closing now discards them."
        confirmLabel="Discard drafts"
        onConfirm={() => {
          setConfirmClose(false);
          reset();
          onClose();
        }}
      />
    </>
  );
}
