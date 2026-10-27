"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, TriangleAlert } from "lucide-react";
import { audioUrl, mmss, type CallDetailData, type Turn } from "@/lib/api/calls";
import { Button } from "@/components/ui/button";
import { ErrorPanel, Skeleton } from "@/components/ui/states";
import { Panel } from "@/components/ui/layout";

const GUTTER = 64;
const BIN_MS = 100;
const SPEEDS = [0.75, 1, 1.25, 1.5];

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Peak per 100 ms of a track, decoded in the browser from the same Range-capable endpoint the player streams. */
async function loadPeaks(url: string, signal: AbortSignal): Promise<number[]> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`audio ${res.status}`);
  const buf = await res.arrayBuffer();
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  try {
    const audio = await ctx.decodeAudioData(buf);
    const data = audio.getChannelData(0);
    const per = Math.max(1, Math.floor((audio.sampleRate * BIN_MS) / 1000));
    const out: number[] = [];
    for (let i = 0; i < data.length; i += per) {
      let m = 0;
      for (let j = i; j < Math.min(i + per, data.length); j++) m = Math.max(m, Math.abs(data[j]));
      out.push(m);
    }
    return out;
  } finally {
    void ctx.close();
  }
}

export type Evidence = { turns: number[]; label: string } | null;

export function AudioPanel({
  call,
  playhead,
  setPlayhead,
  evidence,
  seekRequest,
  onPlayingChange,
}: {
  call: CallDetailData;
  playhead: number;
  setPlayhead: (ms: number) => void;
  evidence: Evidence;
  /** Bumped by the page to seek to a ms position (from transcript clicks, evidence refs, keyboard). */
  seekRequest: { ms: number; n: number } | null;
  onPlayingChange?: (playing: boolean) => void;
}) {
  const turns = useMemo(() => call.turns ?? [], [call.turns]);
  const duration = call.duration_ms ?? Math.max(1000, ...turns.map((t) => t.end_ms));
  const rec = call.recordings ?? {};
  const playTrack = rec.mixed ? "mixed" : rec.original ? "original" : null;
  const twoLanes = !!(rec.caller && rec.agent);
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [peaks, setPeaks] = useState<Record<string, number[]> | null>(null);
  const [peakError, setPeakError] = useState<unknown>(null);
  const [wrap, width] = useWidth();
  const raf = useRef(0);

  // Waveform peaks load independently of playback.
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    if (!playTrack) return;
    const ac = new AbortController();
    // Simulated calls have one track per speaker; uploads have the single recording.
    (twoLanes
      ? Promise.all([loadPeaks(audioUrl(call.id, "caller"), ac.signal), loadPeaks(audioUrl(call.id, "agent"), ac.signal)]).then(([caller, agent]) => ({ caller, agent }))
      : loadPeaks(audioUrl(call.id, playTrack), ac.signal).then((mixed) => ({ mixed }))
    )
      .then((p) => setPeaks(p))
      .catch((e) => {
        if (!ac.signal.aborted) setPeakError(e);
      });
    return () => ac.abort();
  }, [call.id, twoLanes, playTrack, reloadKey]);

  // Playhead follows the audio element.
  useEffect(() => {
    const el = audio.current;
    if (!el) return;
    const tick = () => {
      setPlayhead(el.currentTime * 1000);
      raf.current = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      setPlaying(true);
      onPlayingChange?.(true);
      raf.current = requestAnimationFrame(tick);
    };
    const onPause = () => {
      setPlaying(false);
      onPlayingChange?.(false);
      cancelAnimationFrame(raf.current);
      setPlayhead(el.currentTime * 1000);
    };
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onPause);
    return () => {
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onPause);
      cancelAnimationFrame(raf.current);
    };
  }, [setPlayhead, onPlayingChange]);

  const seek = useCallback(
    (ms: number) => {
      const el = audio.current;
      const t = Math.max(0, Math.min(ms, duration));
      if (el && playTrack) el.currentTime = t / 1000;
      setPlayhead(t);
    },
    [duration, playTrack, setPlayhead],
  );
  useEffect(() => {
    if (seekRequest) seek(seekRequest.ms);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekRequest?.n]);
  useEffect(() => {
    if (audio.current) audio.current.playbackRate = speed;
  }, [speed]);

  const toggle = useCallback(() => {
    const el = audio.current;
    if (!el) return;
    if (el.paused) void el.play().catch(() => setAudioError("The browser could not play this recording."));
    else el.pause();
  }, []);

  // Keyboard: Space play/pause, Left/Right 5 s (00-shared 8). j/k and [ ] are handled by the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target as HTMLElement | null)?.isContentEditable) return;
      if (e.key === " " && tag !== "BUTTON" && tag !== "A") {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowRight") seek((audio.current?.currentTime ?? 0) * 1000 + 5000);
      else if (e.key === "ArrowLeft") seek((audio.current?.currentTime ?? 0) * 1000 - 5000);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seek, toggle]);

  const W = Math.max(0, width - GUTTER);
  const x = (ms: number) => GUTTER + (ms / duration) * W;
  const sorted = useMemo(() => [...turns].sort((a, b) => a.idx - b.idx), [turns]);
  const lat = useMemo(() => {
    const out: { x: number; ms: number; idx: number }[] = [];
    sorted.forEach((t, i) => {
      const prev = sorted[i - 1];
      if (t.speaker === "agent" && prev?.speaker === "caller") out.push({ x: t.start_ms, ms: t.start_ms - prev.end_ms, idx: t.idx });
    });
    return out;
  }, [sorted]);
  const tools = call.tool_calls ?? [];
  const barge = sorted.filter((t) => t.is_barge_in);
  const gaps = useMemo(() => {
    const out: { a: number; b: number }[] = [];
    for (let i = 1; i < sorted.length; i++) if (sorted[i].start_ms - sorted[i - 1].end_ms > 2000) out.push({ a: sorted[i - 1].end_ms, b: sorted[i].start_ms });
    return out;
  }, [sorted]);

  const evTurns = evidence ? sorted.filter((t) => evidence.turns.includes(t.idx)) : [];
  const evA = evTurns.length ? Math.min(...evTurns.map((t) => t.start_ms)) : 0;
  const evB = evTurns.length ? Math.max(...evTurns.map((t) => t.end_ms)) : 0;

  const laneH = 36;
  const rulerH = 18;
  const showLatency = call.source === "simulation";
  const H = rulerH + laneH * 2 + 40 + (showLatency ? 56 + 12 : 8);
  const laneTop = { agent: rulerH, caller: rulerH + laneH + 4, events: rulerH + laneH * 2 + 12, latency: rulerH + laneH * 2 + 56 };
  const maxLat = Math.max(3000, ...lat.map((l) => l.ms));
  const ticks = Array.from({ length: Math.floor(duration / 10000) + 1 }, (_, i) => i * 10000);

  const strokes = (track: number[], top: number, color: string) => {
    let d = "";
    const mid = top + laneH / 2;
    track.forEach((p, i) => {
      const px = x(i * BIN_MS);
      const h = Math.max(0.6, p * (laneH - 4));
      d += `M${px.toFixed(1)} ${(mid - h / 2).toFixed(1)}V${(mid + h / 2).toFixed(1)}`;
    });
    return <path d={d} stroke={color} strokeWidth="1.6" strokeLinecap="butt" fill="none" />;
  };

  const headTitle = (
    <span className="text-xs text-muted">
      {playTrack ?? "no audio"}
      {call.source !== "simulation" && " · uploaded recording"}
    </span>
  );

  return (
    <Panel title="Audio" aux={headTitle} id="audio">
      {playTrack && (
        <audio ref={audio} src={audioUrl(call.id, playTrack)} preload="metadata" onError={() => setAudioError("The recording could not be loaded.")} />
      )}
      {!playTrack ? (
        <p className="text-sm text-muted">No recording for this call. The transcript still works; seeking is disabled.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <Button variant="primary" icon aria-label={playing ? "Pause" : "Play"} title="Space plays or pauses. Left and Right move 5 s. j and k change turn. [ and ] change evidence." onClick={toggle} className="!h-9 !w-9">
              {playing ? <Pause size={16} strokeWidth={1.6} aria-hidden /> : <Play size={16} strokeWidth={1.6} aria-hidden />}
            </Button>
            <span className="mono text-md" aria-label="Playback position">
              {mmss(playhead)} <span className="text-subtle">/ {mmss(duration)}</span>
            </span>
            <div className="ml-auto flex items-center gap-3 text-xs text-muted">
              <Legend color="var(--speaker-agent)" label="Agent" />
              <Legend color="var(--speaker-caller)" label="Caller" />
              <span className="inline-flex items-center gap-1"><span className="h-3 w-4 border border-fail bg-fail-tint" aria-hidden />Evidence</span>
              <span className="inline-flex items-center gap-1"><TriangleAlert size={12} aria-hidden />Barge-in</span>
              <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 bg-fg" aria-hidden />Tool call</span>
              <label className="flex items-center gap-1">
                <span className="sr-only">Speed</span>
                <select aria-label="Playback speed" className="h-6 rounded-xs border border-border-strong bg-surface px-1 text-xs" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                  {SPEEDS.map((s) => (
                    <option key={s} value={s}>{s}x</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          {audioError && <div className="mb-2"><ErrorPanel error={new Error(audioError)} onRetry={() => { setAudioError(null); audio.current?.load(); }} /></div>}
          <div ref={wrap} className="relative w-full select-none">
            {width === 0 || (!peaks && !peakError) ? (
              <div role="status" aria-label="Loading audio" aria-busy="true"><Skeleton className="h-[160px] w-full" /></div>
            ) : peakError ? (
              <ErrorPanel error={peakError} what="the waveform" onRetry={() => { setPeakError(null); setReloadKey((k) => k + 1); }} />
            ) : (
              <svg
                width={width}
                height={H}
                role="img"
                aria-label="Timeline of the call: agent and caller speech, events and agent response latency. The transcript below has the same content as text."
                onClick={(e) => {
                  const r = e.currentTarget.getBoundingClientRect();
                  const px = e.clientX - r.left;
                  if (px >= GUTTER) seek(((px - GUTTER) / W) * duration);
                }}
                className="cursor-pointer"
              >
                {ticks.map((t) => (
                  <g key={t}>
                    <line x1={x(t)} x2={x(t)} y1={rulerH - 4} y2={H} stroke="var(--grid)" />
                    <text x={x(t) + 3} y={11} className="mono" fontSize="10" fill="var(--fg-subtle)">{mmss(t)}</text>
                  </g>
                ))}
                {!twoLanes && (
                  <g>
                    <text x={0} y={laneTop.agent + laneH + 3} className="eyebrow" fontSize="10" fill="var(--fg-subtle)">MIXED</text>
                    {sorted.map((t) => (
                      <rect key={t.idx} x={x(t.start_ms)} y={laneTop.agent} width={Math.max(1, x(t.end_ms) - x(t.start_ms))} height={laneH * 2 + 4} fill={t.speaker === "agent" ? "var(--speaker-agent)" : "var(--speaker-caller)"} opacity="0.16">
                        <title>{t.speaker === "agent" ? "Agent" : "Caller"}, turn {t.idx}</title>
                      </rect>
                    ))}
                    <line x1={GUTTER} x2={GUTTER + W} y1={laneTop.agent + laneH + 2} y2={laneTop.agent + laneH + 2} stroke="var(--border-strong)" strokeWidth="1" opacity="0.5" />
                    {peaks?.mixed && (
                      <path
                        d={peaks.mixed.map((p, i) => `M${x(i * BIN_MS).toFixed(1)} ${(laneTop.agent + laneH + 2 - Math.max(0.6, p * (laneH * 2)) / 2).toFixed(1)}v${Math.max(0.6, p * (laneH * 2)).toFixed(1)}`).join("")}
                        stroke="var(--fg-muted)"
                        strokeWidth="1.6"
                        fill="none"
                      />
                    )}
                  </g>
                )}
                {twoLanes && (["agent", "caller"] as const).map((l) => (
                  <g key={l}>
                    <text x={0} y={laneTop[l] + laneH / 2 + 3} className="eyebrow" fontSize="10" fill="var(--fg-subtle)">{l.toUpperCase()}</text>
                    <line x1={GUTTER} x2={GUTTER + W} y1={laneTop[l] + laneH / 2} y2={laneTop[l] + laneH / 2} stroke={l === "agent" ? "var(--speaker-agent)" : "var(--speaker-caller)"} strokeWidth="1" opacity="0.5" />
                    {peaks?.[l] && strokes(peaks[l], laneTop[l], l === "agent" ? "var(--speaker-agent)" : "var(--speaker-caller)")}
                  </g>
                ))}
                <text x={0} y={laneTop.events + 20} className="eyebrow" fontSize="10" fill="var(--fg-subtle)">EVENTS</text>
                <line x1={GUTTER} x2={GUTTER + W} y1={laneTop.events + 16} y2={laneTop.events + 16} stroke="var(--grid)" />
                {gaps.map((g, i) => (
                  <rect key={i} x={x(g.a)} y={laneTop.events + 12} width={Math.max(2, x(g.b) - x(g.a))} height="8" fill="var(--bg-sunken)" stroke="var(--border-strong)">
                    <title>Silence over 2 s</title>
                  </rect>
                ))}
                {barge.map((t) => (
                  <path key={t.idx} d={`M${x(t.start_ms)} ${laneTop.events + 8}l6 12h-12z`} fill="var(--warn)" stroke="var(--fg)" strokeWidth="0.8"><title>Barge-in at turn {t.idx}</title></path>
                ))}
                {tools.map((tc) => (
                  <rect key={tc.seq} x={x(tc.at_ms) - 4} y={laneTop.events + 12} width="8" height="8" fill="var(--fg)"><title>Tool call {tc.name}</title></rect>
                ))}
                {showLatency && (
                  <g>
                <text x={0} y={laneTop.latency + 12} className="eyebrow" fontSize="10" fill="var(--fg-subtle)">LATENCY</text>
                <line x1={GUTTER} x2={GUTTER + W} y1={laneTop.latency + 56 - (2000 / maxLat) * 50} y2={laneTop.latency + 56 - (2000 / maxLat) * 50} stroke="var(--fg-muted)" strokeDasharray="4 3" />
                <text x={0} y={laneTop.latency + 56 - (2000 / maxLat) * 50 + 3} className="mono" fontSize="9" fill="var(--fg-muted)">2.0 s target</text>
                {lat.map((l) => {
                  const h = (l.ms / maxLat) * 50;
                  const col = l.ms > 2000 ? "var(--fail)" : l.ms > 1000 ? "var(--warn)" : "var(--series-3)";
                  return (
                    <g key={l.idx}>
                      <rect x={x(l.x) - 5} y={laneTop.latency + 56 - h} width="10" height={h} rx="2" fill={col}><title>{(l.ms / 1000).toFixed(1)} s to respond (turn {l.idx})</title></rect>
                      <text x={x(l.x)} y={laneTop.latency + 53 - h} textAnchor="middle" className="mono" fontSize="9" fill="var(--fg-muted)">{(l.ms / 1000).toFixed(1)}</text>
                    </g>
                  );
                })}
                  </g>
                )}
                {evidence && evTurns.length > 0 && (
                  <g>
                    <rect x={x(evA)} y={rulerH - 2} width={Math.max(3, x(evB) - x(evA))} height={H - rulerH} fill="var(--fail)" opacity="0.14" />
                    <line x1={x(evA)} x2={x(evA)} y1={rulerH - 2} y2={H} stroke="var(--fail)" />
                    <line x1={x(evB)} x2={x(evB)} y1={rulerH - 2} y2={H} stroke="var(--fail)" />
                    <text x={x(evA) + 4} y={laneTop.caller + laneH + 8} className="mono" fontSize="10" fill="var(--fail-fg)">{evidence.label}</text>
                  </g>
                )}
                <g aria-hidden>
                  <line x1={x(playhead)} x2={x(playhead)} y1={rulerH - 2} y2={H} stroke="var(--accent)" strokeWidth="2" />
                  <path d={`M${x(playhead) - 5} ${rulerH - 6}h10l-5 7z`} fill="var(--accent)" />
                </g>
              </svg>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="h-2.5 w-2.5" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

export type { Turn };
