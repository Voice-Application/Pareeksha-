"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Flag as FlagIcon } from "lucide-react";
import { api } from "@/lib/api/client";
import { call as callApi } from "@/lib/api/call";
import { listRunItems } from "@/lib/api/runs";
import { CHECK_TAG, getCall, mmss, TAG_DIMENSION } from "@/lib/api/calls";
import { PageHeader } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { PageError, Skeleton } from "@/components/ui/states";
import { StatusPill } from "@/components/ui/measure";
import { useToast } from "@/components/ui/toast";
import { AudioPanel, type Evidence } from "./audio-panel";
import { Transcript, type TurnTags } from "./transcript";
import { ChecksPanel, DimensionsPanel, FailureTagsPanel, MetricsPanel, VerdictPanel } from "./scorecards";
import { PromoteDialog, ReviewSheet } from "./review-dialogs";
import { SpeakersPanel } from "./speakers-panel";

export function CallDetailSkeleton() {
  return (
    <>
      <PageHeader eyebrow="Call" title="" description={<Skeleton className="h-4 w-80" />} />
      <div role="status" aria-label="Loading" aria-busy="true" className="grid gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
        <div className="flex flex-col gap-6">
          <Skeleton className="h-[220px] w-full" />
          <div className="flex flex-col gap-2 rounded-md border border-border bg-surface p-4">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        </div>
        <div className="flex flex-col gap-6">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-40 w-full" />)}</div>
      </div>
    </>
  );
}

const firstSentence = (s: string) => {
  const m = s.match(/^.{20,}?[.!?](\s|$)/);
  return m ? m[0].trim() : s;
};

export function CallDetail({ callId }: { callId: string }) {
  const params = useSearchParams();
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery({
    queryKey: ["call", callId],
    queryFn: () => getCall(callId),
    refetchInterval: (query) => (query.state.data && ["in_progress", "transcribing"].includes(query.state.data.status) ? 2000 : false),
  });
  const c = q.data;
  const agent = useQuery({ queryKey: ["agent", c?.agent_id], enabled: !!c?.agent_id, queryFn: () => callApi(api.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: c!.agent_id! } } })) });
  const run = useQuery({ queryKey: ["run-items", c?.run_id], enabled: !!c?.run_id, queryFn: () => listRunItems(c!.run_id!) });
  const item = run.data?.items.find((i) => i.call_id === callId);

  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence>(null);
  const [seek, setSeek] = useState<{ ms: number; n: number } | null>(null);
  const [review, setReview] = useState<{ reviewer: string; passed: boolean; critical: boolean } | null>(null);
  const [sheet, setSheet] = useState(false);
  const [promote, setPromote] = useState(false);

  const turns = useMemo(() => [...(c?.turns ?? [])].sort((a, b) => a.idx - b.idx), [c?.turns]);
  const ev = c?.evaluation ?? null;

  const goTurn = useCallback(
    (idx: number, ref?: { turns: number[]; label: string }) => {
      const t = turns.find((x) => x.idx === idx);
      if (!t) return;
      setSelected(idx);
      setSeek((s) => ({ ms: t.start_ms, n: (s?.n ?? 0) + 1 }));
      setEvidence(ref ?? { turns: [idx], label: `Evidence #${idx}` });
    },
    [turns],
  );
  const showEvidence = useCallback((ts: number[], label: string) => ts.length && goTurn(Math.min(...ts), { turns: ts, label }), [goTurn]);

  // ?turn=4 opens the page already seeked to that turn.
  const turnParam = params.get("turn");
  useEffect(() => {
    if (turnParam !== null && turns.length) queueMicrotask(() => goTurn(Number(turnParam)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnParam, turns.length]);

  // Failing evidence: dimensions scored 0-2 and failed checks. Tags point at their check's turns, else their dimension's.
  const { evidenceTurns, turnTags, tagList, firstTurn } = useMemo(() => {
    const evSet = new Set<number>();
    const byTag: Record<string, { turns: Set<number>; level: "fail" | "warn" }> = {};
    const dims = ev?.dimensions ?? {};
    for (const d of Object.values(dims)) if (d.score <= 2) (d.evidence_turns ?? []).forEach((n) => evSet.add(n));
    for (const ch of c?.checks ?? []) if (ch.passed === false) (ch.evidence_turns ?? []).forEach((n) => evSet.add(n));
    for (const tag of ev?.failure_types ?? []) {
      const fromCheck = (c?.checks ?? []).filter((ch) => ch.passed === false && CHECK_TAG[ch.check_type] === tag).flatMap((ch) => ch.evidence_turns ?? []);
      const dim = dims[TAG_DIMENSION[tag]];
      // The judge's evidence for the dimension is the better anchor; a check's turns are the fallback.
      const ts = dim?.evidence_turns?.length ? dim.evidence_turns : fromCheck;
      byTag[tag] = { turns: new Set(ts), level: dim && dim.score === 2 ? "warn" : "fail" };
    }
    const tt: TurnTags = {};
    for (const [tag, v] of Object.entries(byTag)) for (const n of v.turns) (tt[n] ??= []).push({ tag, level: v.level });
    const first: Record<string, number | undefined> = {};
    for (const [tag, v] of Object.entries(byTag)) first[tag] = v.turns.size ? Math.min(...v.turns) : undefined;
    return { evidenceTurns: evSet, turnTags: tt, tagList: Object.entries(byTag).map(([tag, v]) => ({ tag, count: v.turns.size, level: v.level })), firstTurn: first };
  }, [ev, c?.checks]);

  const call_source_sim = c?.source === "simulation";
  const latencyByTurn = useMemo(() => {
    const out: Record<number, number> = {};
    turns.forEach((t, i) => {
      const prev = turns[i - 1];
      if (call_source_sim && t.speaker === "agent" && prev?.speaker === "caller") out[t.idx] = t.start_ms - prev.end_ms;
    });
    return out;
  }, [turns, call_source_sim]);

  // j/k previous/next turn, [ ] previous/next evidence group.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.metaKey || e.ctrlKey) return;
      const cur = selected ?? turns.find((t) => playhead >= t.start_ms && playhead < t.end_ms)?.idx ?? -1;
      if (e.key === "j") goTurn(Math.min(turns.length - 1, cur + 1));
      else if (e.key === "k") goTurn(Math.max(0, cur - 1));
      else if (e.key === "]" || e.key === "[") {
        const sorted = [...evidenceTurns].sort((a, b) => a - b);
        const next = e.key === "]" ? sorted.find((n) => n > cur) : [...sorted].reverse().find((n) => n < cur);
        if (next !== undefined) goTurn(next);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, turns, playhead, evidenceTurns, goTurn]);

  if (q.isError) return <PageError error={q.error} onRetry={() => void q.refetch()} backHref="/runs" backLabel="Back to runs" />;
  if (q.isPending) return <CallDetailSkeleton />;
  const call = c!;
  const summary = ev?.summary ?? "";
  const title = ev && ev.status === "ok" && summary ? firstSentence(summary) : `Call ${call.id.slice(0, 8)}`;
  const desc = ev && ev.status === "ok" && summary ? summary.slice(firstSentence(summary).length).trim() : undefined;
  const lineName = item?.noise_profile;
  const sim = call.source === "simulation";
  const failed = ev?.passed === false;

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span>Call {call.id.slice(0, 8)}</span>
            <span aria-hidden>·</span>
            <span>{sim ? "Synthetic caller" : call.source === "upload" ? "Uploaded recording" : "Imported call"}</span>
            {call.language && <><span aria-hidden>·</span><span>{call.language}</span></>}
            {call.status !== "completed" && <StatusPill status={call.status} />}
          </span>
        }
        title={title}
        description={desc}
        actions={
          <>
            <Button onClick={() => { void navigator.clipboard?.writeText(window.location.href); toast("Link copied."); }}>
              <Link2 size={14} strokeWidth={1.6} aria-hidden />
              Copy link
            </Button>
            {ev && ev.status === "ok" && (
              <Button variant={failed ? "primary" : "secondary"} onClick={() => setPromote(true)}>
                <FlagIcon size={14} strokeWidth={1.6} aria-hidden />
                {failed ? "Promote to regression" : "Add as regression test"}
              </Button>
            )}
          </>
        }
      />

      <dl className="mb-6 grid divide-x divide-border overflow-hidden rounded-md border border-border bg-surface max-[860px]:grid-cols-2 max-[860px]:divide-x-0 grid-cols-2 min-[860px]:grid-cols-3 min-[1180px]:grid-cols-6">
        <Meta label="Agent" value={agent.data?.name ?? "-"} sub={agent.data?.glass_box ? "glass-box" : undefined} />
        <Meta label="Scenario" value={item?.scenario ?? (sim ? "-" : "Agent goals")} sub={call.run_id ? <Link className="underline-offset-2 hover:underline" href={`/runs/${call.run_id}`}>open run</Link> : undefined} />
        <Meta label="Persona" value={item?.persona ?? "-"} />
        <Meta label="Line" value={lineName ?? (sim ? "-" : "original recording")} />
        <Meta label="Duration" value={call.duration_ms ? mmss(call.duration_ms) : "-"} mono sub={`${turns.length} turns`} />
        <Meta label="Judge" value={ev ? `Confidence ${ev.confidence ?? "-"}` : "-"} sub={ev?.judge_model} />
      </dl>

      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
        <div className="flex min-w-0 flex-col gap-6">
          <AudioPanel call={call} playhead={playhead} setPlayhead={setPlayhead} evidence={evidence} seekRequest={seek} onPlayingChange={setPlaying} />
          {!sim && call.speaker_map && Object.keys(call.speaker_map).length > 0 && <SpeakersPanel callId={callId} map={call.speaker_map} />}
          <Transcript call={call} playhead={playhead} playing={playing} selected={selected} onSelect={(i) => goTurn(i)} evidenceTurns={evidenceTurns} turnTags={turnTags} latencyByTurn={latencyByTurn} />
        </div>
        <div className="flex min-w-0 flex-col gap-6 max-[1180px]:order-first">
          <VerdictPanel ev={ev} status={call.status} onOverride={() => setSheet(true)} onReevaluate={() => {
            void callApi(api.POST("/api/v1/calls/{call_id}/reevaluate", { params: { path: { call_id: callId } }, body: {} as never })).then(() => { toast("Re-evaluation started."); void qc.invalidateQueries({ queryKey: ["call", callId] }); }).catch(() => toast("Re-evaluation is not available in this build yet.", { tone: "error" }));
          }} review={review} />
          {ev && ev.status === "ok" && <FailureTagsPanel tags={tagList} onTurn={(n) => goTurn(n)} firstTurn={firstTurn} />}
          {ev && ev.status === "ok" && <DimensionsPanel ev={ev} onEvidence={showEvidence} />}
          <ChecksPanel checks={call.checks ?? []} onEvidence={showEvidence} />
          <MetricsPanel m={call.metrics} turns={turns} />
        </div>
      </div>
      {ev && <ReviewSheet open={sheet} onClose={() => setSheet(false)} callId={callId} ev={ev} onSaved={setReview} />}
      <PromoteDialog open={promote} onClose={() => setPromote(false)} callId={callId} ev={ev} />
    </>
  );
}

function Meta({ label, value, sub, mono }: { label: string; value: string; sub?: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <dt className="eyebrow">{label}</dt>
      <dd className="min-w-0">
        <span className={`mt-0.5 block truncate text-sm font-medium ${mono ? "mono" : ""}`} title={value}>{value}</span>
        {sub && <span className="block truncate text-xs text-subtle">{sub}</span>}
      </dd>
    </div>
  );
}
