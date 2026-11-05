"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { overallStep } from "@/components/ui/measure";
import { CALLERS, CALLER_ROLE, LINES, RUN_CALLS, SCENARIOS, type RunCall } from "./run-data";

const STEP_MS = 420;
const mmss = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.round((ms % 60000) / 1000)).padStart(2, "0")}`;
const fmt = (n: number) => String(Number(n.toFixed(2)));

/** Top failure codes across the whole run, most common first. */
const TOP_TAGS = Object.entries(
  RUN_CALLS.flatMap((c) => c.tags).reduce<Record<string, number>>((acc, t) => ((acc[t] = (acc[t] ?? 0) + 1), acc), {}),
)
  .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  .slice(0, 4);

/**
 * The planted-bugs run, replayed in the order its calls finished. Renders complete without script;
 * with script it replays once when it first comes into view, unless the visitor prefers reduced motion.
 */
export function RunReplay() {
  const [shown, setShown] = useState(RUN_CALLS.length);
  const [playing, setPlaying] = useState(false);
  const [line, setLine] = useState<RunCall["line"]>("pstn_8k_alaw");
  const [tag, setTag] = useState<string | null>(null);
  const [active, setActive] = useState<RunCall | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    const el = root.current;
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true;
        setShown(0);
        setActive(null);
        setPlaying(true);
      }
    }, { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setShown((n) => {
        if (n + 1 >= RUN_CALLS.length) setPlaying(false);
        return Math.min(RUN_CALLS.length, n + 1);
      });
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [playing]);

  const scored = RUN_CALLS.slice(0, shown);
  const tally = useMemo(
    () => ({
      n: scored.length,
      critical: scored.filter((c) => c.critical).length,
      passed: scored.filter((c) => c.passed).length,
      mean: scored.length ? scored.reduce((a, c) => a + c.score, 0) / scored.length : null,
    }),
    [scored],
  );
  const done = shown >= RUN_CALLS.length;
  const pickLine = (id: RunCall["line"]) => { setLine(id); setActive(null); };
  // Only show a call that is on the current line and already scored in the replay.
  const detail = active && active.line === line && RUN_CALLS.indexOf(active) < shown ? active : null;

  return (
    <div ref={root} className="lp-rp" data-kind="product">
      <div className="lp-rp__head">
        <div className="lp-rp__title">
          <p className="lp-rp__name">Run <code>planted-bugs</code></p>
          <p className="lp-rp__state">{done ? "Finished: 18 of 18 calls scored" : `Scoring, ${shown} of 18 calls done`}</p>
        </div>
        <div className="lp-rp__controls">
          <div className="lp-seg" role="radiogroup" aria-label="Line">
            {LINES.map((l, i) => (
              <button
                key={l.id}
                type="button"
                role="radio"
                aria-checked={line === l.id}
                tabIndex={line === l.id ? 0 : -1}
                onClick={() => pickLine(l.id)}
                onKeyDown={(e) => {
                  const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
                  if (!step) return;
                  e.preventDefault();
                  const next = LINES[(i + step + LINES.length) % LINES.length];
                  pickLine(next.id);
                  (e.currentTarget.parentElement?.querySelector(`[data-line="${next.id}"]`) as HTMLButtonElement | null)?.focus();
                }}
                data-line={l.id}
                className="lp-seg__opt"
              >
                {l.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn btn--quiet lp-rp__play"
            onClick={() => {
              if (done) { setShown(0); setActive(null); setPlaying(true); } else setPlaying((p) => !p);
            }}
          >
            {done ? "Replay" : playing ? "Pause" : "Resume"}
          </button>
        </div>
      </div>

      <div className="lp-rp__body">
        <div className="lp-rp__grid" role="group" aria-label={`Scores by scenario and caller on the ${LINES.find((l) => l.id === line)!.label.toLowerCase()}`}>
          <span aria-hidden />
          {CALLERS.map((who) => (
            <span key={who} className="lp-rp__col">{who}</span>
          ))}
          {SCENARIOS.map((sc) => (
            <div key={sc} className="lp-rp__r">
              <span className="lp-rp__row">{sc}</span>
              {CALLERS.map((who) => {
                const i = RUN_CALLS.findIndex((x) => x.scenario === sc && x.caller === who && x.line === line);
                const call = RUN_CALLS[i];
                const on = i < shown;
                const dim = !!tag && on && !call.tags.includes(tag);
                return (
                  <button
                    key={who}
                    type="button"
                    className="lp-rp__cell"
                    data-step={on ? overallStep(call.score) : undefined}
                    data-critical={on && call.critical ? "" : undefined}
                    data-dim={dim ? "" : undefined}
                    aria-label={on ? `${sc}, ${who}: ${fmt(call.score)}${call.critical ? ", critical" : ""}${tag ? (dim ? `, does not match ${tag}` : `, matches ${tag}`) : ""}` : `${sc}, ${who}: not scored yet`}
                    onMouseEnter={() => on && setActive(call)}
                    onFocus={() => on && setActive(call)}
                    onClick={() => on && setActive(call)}
                  >
                    <span className="num">{on ? fmt(call.score) : "..."}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <aside className="lp-rp__detail" aria-live="polite">
          {detail ? (
            <>
              <p className="lp-rp__dscore num" data-step={overallStep(detail.score)}>{fmt(detail.score)}<span>/100</span></p>
              <p className="lp-rp__dverdict">{detail.critical ? "Critical failure" : "Fail"}, <span className="num">{mmss(detail.ms)}</span></p>
              <p className="lp-rp__dwho">{detail.scenario}</p>
              <p className="lp-rp__dsub">{detail.caller}, {CALLER_ROLE[detail.caller]}</p>
              <ul className="lp-rp__dtags">
                {detail.tags.slice(0, 3).map((t) => <li key={t}><code>{t}</code></li>)}
                {detail.tags.length > 3 && <li className="lp-rp__dmore">and {detail.tags.length - 3} more</li>}
              </ul>
            </>
          ) : (
            <p className="lp-rp__hint">Point at a score to read that call.</p>
          )}
        </aside>
      </div>

      <dl className="lp-rp__tally">
        <div><dt>Scored</dt><dd className="num">{tally.n}<span>/18</span></dd></div>
        <div><dt>Critical</dt><dd className="num" data-tone="fail">{tally.critical}</dd></div>
        <div><dt>Passed</dt><dd className="num">{tally.passed}</dd></div>
        <div><dt>Mean score</dt><dd className="num">{tally.mean == null ? "-" : tally.mean.toFixed(1)}</dd></div>
      </dl>

      <div className="lp-rp__tags" role="group" aria-label="Highlight calls with this failure">
        {TOP_TAGS.map(([t, n]) => (
          <button key={t} type="button" className="lp-chip" aria-pressed={tag === t} onClick={() => setTag((x) => (x === t ? null : t))}>
            <code>{t}</code>
            <span className="num">{n}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
