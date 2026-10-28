"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";

/** Uploads only: the diarisation mapping and the swap that re-evaluates the call (10-call-detail). */
export function SpeakersPanel({ callId, map }: { callId: string; map: Record<string, "caller" | "agent"> }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [confirm, setConfirm] = useState(false);
  const swapped = Object.fromEntries(Object.entries(map).map(([k, v]) => [k, v === "agent" ? "caller" : "agent"])) as Record<string, "caller" | "agent">;
  const swap = useMutation({
    mutationFn: () => call(api.POST("/api/v1/calls/{call_id}/speaker-map", { params: { path: { call_id: callId } }, body: swapped })),
    onSuccess: () => {
      toast("Speakers swapped. The call is being re-evaluated.");
      setConfirm(false);
      void qc.invalidateQueries({ queryKey: ["call", callId] });
    },
    onError: (e) => {
      setConfirm(false);
      toast(e instanceof ApiError && e.code === "not_implemented" ? "Swapping speakers is not available in this build yet." : `Could not swap: ${e instanceof ApiError ? e.userMessage() : "request failed"}`, { tone: "error" });
    },
  });
  return (
    <Panel title="Speakers" aux={<Button onClick={() => setConfirm(true)}><ArrowLeftRight size={14} strokeWidth={1.6} aria-hidden />Swap speakers</Button>}>
      <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        {Object.entries(map).map(([sp, role]) => (
          <li key={sp}>
            Speaker <span className="mono">{sp}</span> = <span className="font-medium">{role === "agent" ? "Agent" : "Caller"}</span>
          </li>
        ))}
      </ul>
      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} title="Swap speakers" body="Swap who is the agent and who is the caller? The call is re-evaluated, which takes about a minute." confirmLabel="Swap and re-evaluate" busy={swap.isPending} onConfirm={() => swap.mutate()} />
    </Panel>
  );
}
