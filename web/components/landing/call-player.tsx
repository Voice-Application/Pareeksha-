"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { CALL_AUDIO, CALL_CALLER, CALL_CRITICAL, CALL_LINE, CALL_MS, CALL_SCORE, CALL_TAGS, CALL_TURNS, PEAKS_AGENT, PEAKS_CALLER } from "./call-data";

const mmss = (ms: number) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const W = 720, LANE = 44, GAP = 14, H = LANE * 2 + GAP;

/** Bars for one speaker lane, drawn from precomputed peaks. Decorative: the transcript carries the same content. */
function Lane({ peaks, y, cls }: { peaks: number[]; y: number; cls: string }) {
  const bw = W / peaks.length;
  return (
    <g className={cls}>
      {peaks.map((p, i) => {
        const h = Math.max(1, p * (LANE - 4));
        return <rect key={i} x={i * bw + 0.5} y={y + (LANE - h) / 2} width={Math.max(1, bw - 1)} height={h} rx={1} />;
      })}
    </g>
  );
}

/**
 * The real call: its mixed recording, both speakers' waveforms, the transcript, and the failure codes the judge
 * raised. Picking a code marks the turns it cites and moves the audio to the first of them.
 */
export function CallPlayer() {
  const audio = useRef<HTMLAudioElement>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tag, setTag] = useState<string>(CALL_TAGS.find((x) => x.tag === "language_mismatch")?.tag ?? CALL_TAGS[0].tag);
  const [failed, setFailed] = useState(false);

  const cited = useMemo(() => new Set(CALL_TAGS.find((x) => x.tag === tag)?.turns ?? []), [tag]);
  const current = CALL_TURNS.find((x) => t >= x.start && t < x.end)?.idx ?? null;

  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    let raf = 0;
    const tick = () => { setT(a.currentTime * 1000); raf = requestAnimationFrame(tick); };
    const onPlay = () => { setPlaying(true); raf = requestAnimationFrame(tick); };
    const onStop = () => { setPlaying(false); cancelAnimationFrame(raf); setT(a.currentTime * 1000); };
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onStop);
    a.addEventListener("ended", onStop);
    const onSeeked = () => setT(a.currentTime * 1000);
    const onError = () => setFailed(true);
    a.addEventListener("seeked", onSeeked);
    a.addEventListener("error", onError);
    return () => { cancelAnimationFrame(raf); a.removeEventListener("play", onPlay); a.removeEventListener("pause", onStop); a.removeEventListener("ended", onStop); a.removeEventListener("seeked", onSeeked); a.removeEventListener("error", onError); };
  }, []);

  const seek = (ms: number, play = false) => {
    const a = audio.current;
    if (!a) return;
    a.currentTime = Math.max(0, ms) / 1000;
    setT(ms);
    if (play) void a.play().catch(() => setFailed(true));
  };
  const toggle = () => {
    const a = audio.current;
    if (!a) return;
    if (a.paused) void a.play().catch(() => setFailed(true));
    else a.pause();
  };
  const pick = (next: string) => {
    setTag(next);
    const first = CALL_TAGS.find((x) => x.tag === next)?.turns[0];
    const turn = CALL_TURNS.find((x) => x.idx === first);
    if (turn) seek(turn.start);
  };
  const x = (ms: number) => (ms / CALL_MS) * W;

  return (
    <div className="lp-call">
      <div className="lp-call__codes" role="group" aria-label="Failure codes the judge raised on this call">
        {CALL_TAGS.map((c) => (
          <button key={c.tag} type="button" className="lp-chip lp-chip--fail" aria-pressed={tag === c.tag} onClick={() => pick(c.tag)}>
            <code>{c.tag}</code>
            <span className="num">{c.turns.length ? `#${c.turns.join(" #")}` : "-"}</span>
          </button>
        ))}
      </div>

      <div className="lp-call__panel" data-kind="product">
        <div className="lp-call__head">
          <button type="button" className="lp-call__play" onClick={toggle} aria-label={playing ? "Pause the call" : "Play the call"} disabled={failed}>
            {playing ? <Pause size={18} strokeWidth={1.8} aria-hidden /> : <Play size={18} strokeWidth={1.8} aria-hidden />}
          </button>
          <p className="lp-call__clock num" aria-live="off"><span>{mmss(t)}</span> / {mmss(CALL_MS)}</p>
          <p className="lp-call__meta">{CALL_CALLER}, <code>{CALL_LINE}</code></p>
          <p className="lp-call__score num" data-critical={CALL_CRITICAL ? "" : undefined}>{CALL_SCORE}<span>/100</span></p>
        </div>
        {failed && <p className="lp-call__err" role="status">The recording could not be loaded. The transcript below is the same call.</p>}

        <div className="lp-call__track">
        <div className="lp-call__lanes" aria-hidden><span>Agent</span><span>Caller</span></div>
        <svg
          className="lp-call__wave"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Waveform of the call: the agent on top, the caller below. Click to move the audio."
          onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * CALL_MS); }}
        >
          {CALL_TURNS.filter((tu) => cited.has(tu.idx)).map((tu) => (
            <rect key={tu.idx} className="lp-call__band" x={x(tu.start)} y={0} width={x(tu.end) - x(tu.start)} height={H} rx={4} />
          ))}
          <Lane peaks={PEAKS_AGENT} y={0} cls="lp-call__agent" />
          <Lane peaks={PEAKS_CALLER} y={LANE + GAP} cls="lp-call__caller" />
          <line className="lp-call__head-line" x1={0} x2={0} y1={0} y2={H} style={{ transform: `translateX(${x(t)}px)` }} />
        </svg>
        </div>

        <ol className="lp-call__turns">
          {CALL_TURNS.map((tu) => (
            <li key={tu.idx} data-cited={cited.has(tu.idx) ? "" : undefined} data-now={current === tu.idx ? "" : undefined}>
              <button type="button" className="lp-call__turn" onClick={() => seek(tu.start, true)} aria-label={`Play turn ${tu.idx}, ${tu.speaker}, from ${mmss(tu.start)}`}>
                <span className="num">{mmss(tu.start)}</span>
                <span className="lp-call__who" data-speaker={tu.speaker}>{tu.speaker === "agent" ? "Agent" : "Caller"}</span>
              </button>
              <div className="lp-call__text">
                <p lang="kn">{tu.text}</p>
                {tu.heard && <p className="lp-call__heard"><span>Agent heard</span> <span lang="kn">{tu.heard}</span></p>}
                {cited.has(tu.idx) && <p className="lp-call__cite"><code>{tag}</code> cites turn {tu.idx}</p>}
              </div>
            </li>
          ))}
        </ol>
        <audio ref={audio} src={CALL_AUDIO} preload="metadata" />
      </div>
    </div>
  );
}
