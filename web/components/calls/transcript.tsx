"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { TriangleAlert } from "lucide-react";
import { mmss, type CallDetailData, type Turn } from "@/lib/api/calls";
import { Panel } from "@/components/ui/layout";
import { Segmented } from "@/components/ui/field";
import { Button } from "@/components/ui/button";
import { TagChip } from "@/components/ui/measure";
import { cn } from "@/lib/utils";

export type TurnTags = Record<number, { tag: string; level: "fail" | "warn"; reason?: string }[]>;
type Filter = "all" | "evidence" | "agent" | "caller";

const LANG_ATTR: Record<string, string> = { "kn-IN": "kn", "hi-IN": "hi", "en-IN": "en" };
const norm = (w: string) => w.toLowerCase().replace(/[.,?!।]/g, "");

/** Words the agent heard that the caller did not say are the likely misrecognitions; they carry weight 500 in fail colour. */
function heardWords(truth: string, heard: string) {
  const t = new Set(truth.split(/\s+/).map(norm));
  return heard.split(/\s+/).map((w, i) => (
    <span key={i} className={t.has(norm(w)) ? undefined : "font-medium text-fail-fg"}>
      {w}{" "}
    </span>
  ));
}

export function Transcript({
  call,
  playhead,
  playing,
  selected,
  onSelect,
  evidenceTurns,
  turnTags,
  latencyByTurn,
}: {
  call: CallDetailData;
  playhead: number;
  playing: boolean;
  selected: number | null;
  onSelect: (idx: number) => void;
  /** All turns cited as evidence by failing dimensions or checks, and those of the item being inspected. */
  evidenceTurns: Set<number>;
  turnTags: TurnTags;
  latencyByTurn: Record<number, number>;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const turns = useMemo(() => [...(call.turns ?? [])].sort((a, b) => a.idx - b.idx), [call.turns]);
  const shown = turns.filter((t) => (filter === "all" ? true : filter === "evidence" ? evidenceTurns.has(t.idx) : t.speaker === filter));
  const current = turns.find((t) => playhead >= t.start_ms && playhead < t.end_ms)?.idx ?? null;
  const box = useRef<HTMLOListElement>(null);
  const lastUser = useRef(0);
  const [away, setAway] = useState(false);
  const simulated = call.source === "simulation";

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const mark = () => {
      lastUser.current = Date.now();
    };
    el.addEventListener("wheel", mark, { passive: true });
    el.addEventListener("touchmove", mark, { passive: true });
    return () => {
      el.removeEventListener("wheel", mark);
      el.removeEventListener("touchmove", mark);
    };
  }, []);

  // Follow the playhead unless the reader scrolled in the last 5 s.
  useEffect(() => {
    if (!playing || current === null) return;
    if (Date.now() - lastUser.current < 5000) {
      setAway(true);
      return;
    }
    setAway(false);
    document.getElementById(`turn-${current}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [current, playing]);

  // Selecting a turn (link, evidence ref, j/k) scrolls it into view.
  useEffect(() => {
    if (selected !== null) document.getElementById(`turn-${selected}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selected]);

  const toolsByTurn = useMemo(() => {
    const m: Record<number, NonNullable<CallDetailData["tool_calls"]>> = {};
    for (const tc of call.tool_calls ?? []) if (tc.turn_idx != null) (m[tc.turn_idx] ??= []).push(tc);
    return m;
  }, [call.tool_calls]);

  return (
    <Panel
      title="Transcript"
      bodyClassName="p-0"
      aux={
        <Segmented
          label="Filter turns"
          hideLabel
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `All ${turns.length}` },
            { value: "evidence", label: `Evidence ${evidenceTurns.size}` },
            { value: "agent", label: "Agent" },
            { value: "caller", label: "Caller" },
          ]}
        />
      }
    >
      <div className="relative">
        {away && playing && (
          <Button className="absolute left-1/2 top-2 z-10 -translate-x-1/2 shadow-[var(--shadow-float)]" onClick={() => { lastUser.current = 0; setAway(false); if (current !== null) document.getElementById(`turn-${current}`)?.scrollIntoView({ block: "center", behavior: "smooth" }); }}>
            Jump to current
          </Button>
        )}
        {shown.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted">{turns.length ? "No turns match this filter." : "No transcript yet."}</p>
        ) : (
          <ol ref={box} className="max-h-[720px] overflow-y-auto" aria-label="Transcript turns">
            {shown.map((t) => (
              <TurnRow
                key={t.idx}
                t={t}
                playing={current === t.idx}
                selected={selected === t.idx}
                evidence={evidenceTurns.has(t.idx)}
                onSelect={onSelect}
                tags={turnTags[t.idx] ?? []}
                latency={latencyByTurn[t.idx]}
                tools={toolsByTurn[t.idx] ?? []}
                simulated={simulated}
                lang={LANG_ATTR[t.language_detected ?? call.language ?? ""] ?? "en"}
              />
            ))}
          </ol>
        )}
      </div>
    </Panel>
  );
}

function TurnRow({ t, playing, selected, evidence, onSelect, tags, latency, tools, simulated, lang }: { t: Turn; playing: boolean; selected: boolean; evidence: boolean; onSelect: (i: number) => void; tags: TurnTags[number]; latency?: number; tools: NonNullable<CallDetailData["tool_calls"]>; simulated: boolean; lang: string }) {
  const heard = simulated && t.speaker === "caller" && t.ground_truth_text && t.agent_heard_text && norm(t.ground_truth_text) !== norm(t.agent_heard_text);
  return (
    <li
      id={`turn-${t.idx}`}
      aria-current={playing ? "true" : undefined}
      className={cn("border-b border-border last:border-0", evidence && "border-l-[3px] border-l-fail bg-fail-tint", playing && !evidence && "bg-selected", selected && "outline outline-2 -outline-offset-2 outline-accent")}
    >
      <div className="grid grid-cols-[64px_72px_1fr_16px] gap-x-2 px-4 py-3 max-[560px]:grid-cols-[52px_1fr_16px]">
        <button type="button" onClick={() => onSelect(t.idx)} className="mono self-start text-left text-xs text-muted hover:text-accent-fg" aria-label={`Seek to turn ${t.idx} at ${mmss(t.start_ms)}`}>
          {mmss(t.start_ms)}
          <br />#{t.idx}
        </button>
        <span className="flex items-start gap-1.5 text-sm font-medium max-[560px]:hidden" style={{ color: t.speaker === "agent" ? "var(--speaker-agent)" : "var(--fg-muted)" }}>
          <span className="mt-1.5 h-2 w-2 shrink-0" style={{ background: t.speaker === "agent" ? "var(--speaker-agent)" : "var(--speaker-caller)" }} aria-hidden />
          {t.speaker === "agent" ? "Agent" : "Caller"}
        </span>
        <div className="min-w-0">
          <p lang={lang} className={cn("text-base", (lang === "kn" || lang === "hi") && "leading-[1.75]")}>
            <span className="sr-only">{t.speaker === "agent" ? "Agent: " : "Caller: "}</span>
            {t.text}
          </p>
          {heard ? (
            <p className="mono mt-1.5 rounded-xs bg-sunken px-2 py-1 text-xs" lang={lang}>
              <span className="text-subtle">AGENT STT HEARD </span>
              {heardWords(t.ground_truth_text!, t.agent_heard_text!)}
              <span className="ml-1 block text-subtle" lang={lang}>caller said: {t.ground_truth_text}</span>
            </p>
          ) : null}
          {tools.map((tc) => (
            <p key={tc.seq} className="mono mt-1.5 rounded-xs bg-sunken px-2 py-1 text-xs">
              <span className="text-subtle">TOOL CALL </span>
              {tc.name}({Object.entries(tc.arguments ?? {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")}) at {mmss(tc.at_ms)}
            </p>
          ))}
          {t.is_barge_in && (
            <p className="mt-1.5 flex items-center gap-1 text-xs text-warn-fg">
              <TriangleAlert size={12} strokeWidth={1.6} aria-hidden />
              Caller interrupted at {mmss(t.start_ms)}.
            </p>
          )}
          {(tags.length > 0 || latency !== undefined) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {latency !== undefined && (
                <span className={cn("mono inline-flex h-6 items-center gap-1 rounded-xs border px-1.5 text-xs", latency > 2000 ? "border-fail bg-fail-tint text-fail-fg" : latency > 1000 ? "border-warn bg-warn-tint text-warn-fg" : "border-border-strong text-muted")}>
                  {latency > 1000 && <TriangleAlert size={12} strokeWidth={1.6} aria-hidden />}
                  {(latency / 1000).toFixed(1)} s to respond
                </span>
              )}
              {tags.map((tg) => (
                <TagChip key={tg.tag} tag={tg.tag} level={tg.level} />
              ))}
            </div>
          )}
        </div>
        <span className="mt-2 h-2 w-2 justify-self-end rounded-full" style={{ background: playing ? "var(--accent)" : "transparent" }} aria-hidden />
      </div>
    </li>
  );
}
