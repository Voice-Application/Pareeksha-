"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { RUBRIC, type CallDetailData } from "@/lib/api/calls";
import { failureTypeCopy } from "@/components/ui/measure";
import { Button } from "@/components/ui/button";
import { Dialog, Sheet } from "@/components/ui/overlay";
import { NumberField, SelectField, Segmented, Switch, TextAreaField, TextField } from "@/components/ui/field";
import { Strip } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";

function failure(e: unknown): string {
  if (e instanceof ApiError && e.code === "not_implemented") return "This action is not available in this build yet.";
  return e instanceof ApiError ? e.userMessage() : "The request failed.";
}

export function ReviewSheet({ open, onClose, callId, ev, onSaved }: { open: boolean; onClose: () => void; callId: string; ev: NonNullable<CallDetailData["evaluation"]>; onSaved: (r: { reviewer: string; passed: boolean; critical: boolean }) => void }) {
  const { toast } = useToast();
  const [reviewer, setReviewer] = useState("");
  const [passed, setPassed] = useState(ev.passed ?? false);
  const [critical, setCritical] = useState(ev.critical_failure);
  const [dims, setDims] = useState<Record<string, number>>(() => Object.fromEntries(RUBRIC.map((d) => [d.key, ev.dimensions?.[d.key]?.score ?? 2])));
  const [notes, setNotes] = useState("");
  const save = useMutation({
    mutationFn: () =>
      call(api.POST("/api/v1/calls/{call_id}/review", { params: { path: { call_id: callId } }, body: { reviewer: reviewer.trim(), passed, critical_failure: critical, dimensions: Object.fromEntries(Object.entries(dims).map(([k, v]) => [k, { score: v }])), notes } })),
    onSuccess: () => {
      toast("Review saved.");
      onSaved({ reviewer: reviewer.trim(), passed, critical });
      onClose();
    },
  });
  const invalid = reviewer.trim().length === 0;
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Override judge score"
      footer={
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} disabled={invalid} onClick={() => save.mutate()}>
            Save review
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {save.isError && <Strip tone="error">{failure(save.error)}</Strip>}
        <p className="text-sm text-muted">Your review is stored next to the judge verdict. It never replaces it, and it feeds calibration.</p>
        <TextField label="Reviewer name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} error={invalid && save.isError ? "Enter your name" : undefined} />
        <Switch label="Passed" checked={passed} onChange={setPassed} />
        <Switch label="Critical failure" checked={critical} onChange={setCritical} />
        {RUBRIC.map((d) => (
          <Segmented key={d.key} label={`${d.label} (judge: ${ev.dimensions?.[d.key]?.score ?? "-"})`} value={dims[d.key]} onChange={(v) => setDims((s) => ({ ...s, [d.key]: v }))} options={[0, 1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))} />
        ))}
        <TextAreaField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
    </Sheet>
  );
}

export function PromoteDialog({ open, onClose, callId, ev }: { open: boolean; onClose: () => void; callId: string; ev: CallDetailData["evaluation"] }) {
  const { toast } = useToast();
  const types = Object.keys(failureTypeCopy);
  const [failureType, setFailureType] = useState<string>(ev?.failure_types?.[0] ?? "wrong_fact");
  const [status, setStatus] = useState<"blocking" | "scheduled" | "manual">("blocking");
  const [baseline, setBaseline] = useState(80);
  const [notes, setNotes] = useState("");
  const [done, setDone] = useState<{ scenario_id: string; regression_test_id: string } | null>(null);
  const promote = useMutation({
    mutationFn: () => call(api.POST("/api/v1/calls/{call_id}/promote", { params: { path: { call_id: callId } }, body: { failure_type: failureType as never, status, baseline_score: baseline, notes } })),
    onSuccess: (r) => {
      setDone(r);
      toast("Promoted to a regression test.");
    },
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Promote to regression"
      footer={
        done ? (
          <Button onClick={onClose}>Close</Button>
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" loading={promote.isPending} onClick={() => promote.mutate()}>
              Promote to regression
            </Button>
          </>
        )
      }
    >
      {done ? (
        <p className="text-sm">
          Created <Link className="text-accent-fg underline" href="/scenarios">a scenario</Link> and <Link className="text-accent-fg underline" href="/regression">a regression test</Link>.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {promote.isError && <Strip tone="error">{failure(promote.error)}</Strip>}
          <SelectField label="Failure type" value={failureType} onChange={(e) => setFailureType(e.target.value)}>
            {types.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </SelectField>
          <SelectField label="Status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {["blocking", "scheduled", "manual"].map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </SelectField>
          <NumberField label="Baseline score" help="Future runs must score at least baseline minus tolerance 5." min={0} max={100} value={baseline} onChange={(e) => setBaseline(Number(e.target.value))} />
          <TextAreaField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      )}
    </Dialog>
  );
}
