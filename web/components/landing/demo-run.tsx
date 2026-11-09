"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DEMO_PROMPT, DEMO_TURNS, DEMO_VERDICT } from "./demo-data";

/**
 * A self-playing demo of one run: the prompt appears, the caller and agent exchange turns, then the
 * verdict lands. No backend — it steps through baked sample data on a timer. Honours reduced motion
 * by showing the finished state at once, and offers play/pause/replay.
 */

// The ordered beats of the demo. Each adds one more visible piece.
const STEPS = [
  "prompt", // the system prompt is in
  "turn-0", // caller asks
  "turn-1", // agent answers (and breaks a rule)
  "verdict", // the score lands
] as const;
const LAST = STEPS.length - 1;
const BEAT_MS = 1400;

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export function DemoRun() {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(true);
  const reduced = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    reduced.current = prefersReducedMotion();
    if (reduced.current) {
      setStep(LAST);
      setPlaying(false);
    }
  }, []);

  useEffect(() => {
    // Only schedule the next beat while playing and there is one left; at the end we simply stop
    // scheduling (no setState here). The controls derive "at end" from `step`, not `playing`.
    if (!playing || reduced.current || step >= LAST) return;
    timer.current = setTimeout(() => setStep((s) => Math.min(s + 1, LAST)), BEAT_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [playing, step]);

  const replay = useCallback(() => {
    setStep(0);
    setPlaying(true);
  }, []);

  const atEnd = step >= LAST;
  const show = (name: (typeof STEPS)[number]) => step >= STEPS.indexOf(name);

  return (
    <div className="lp-demo" aria-label="A sample run, played out">
      <div className="lp-demo__head">
        <span className="lp-demo__tag">Sample run</span>
        <div className="lp-demo__controls">
          {atEnd ? (
            <button type="button" className="lp-demo__btn" onClick={replay}>
              Replay
            </button>
          ) : (
            <button type="button" className="lp-demo__btn" onClick={() => setPlaying((p) => !p)} aria-pressed={!playing}>
              {playing ? "Pause" : "Play"}
            </button>
          )}
        </div>
      </div>

      {/* Prompt */}
      <div className={`lp-demo__block ${show("prompt") ? "is-in" : ""}`}>
        <p className="lp-demo__label">System prompt</p>
        <p className="lp-demo__prompt">{DEMO_PROMPT}</p>
      </div>

      {/* Conversation */}
      <div className="lp-demo__convo" aria-live="polite">
        {DEMO_TURNS.map((t, i) => (
          <div key={i} className={`lp-demo__turn lp-demo__turn--${t.speaker} ${show(`turn-${i}` as (typeof STEPS)[number]) ? "is-in" : ""}`}>
            <span className="lp-demo__who">{t.speaker === "caller" ? "Caller" : "Agent"}</span>
            <p className="lp-demo__text">{t.text}</p>
            {t.broke && show("verdict") && (
              <p className="lp-demo__broke" role="note">
                Broke a rule: {t.broke}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Verdict */}
      <div className={`lp-demo__verdict ${show("verdict") ? "is-in" : ""}`} aria-hidden={!show("verdict")}>
        <div className="lp-demo__vtop">
          <span className="lp-demo__badge">Critical failure</span>
          <span className="lp-demo__rubric mono">{DEMO_VERDICT.rubric}</span>
        </div>
        <p className="lp-demo__label">Overall score</p>
        <div className="lp-demo__meter" role="img" aria-label={`Overall score ${DEMO_VERDICT.score} of 100, pass line ${DEMO_VERDICT.passLine}`}>
          <span className="lp-demo__meter-fill" style={{ width: `${DEMO_VERDICT.score}%` }} />
          <span className="lp-demo__meter-line" style={{ left: `${DEMO_VERDICT.passLine}%` }} />
        </div>
        <p className="lp-demo__score">
          <strong>{DEMO_VERDICT.score}</strong> / 100 <span className="lp-demo__passline">pass line {DEMO_VERDICT.passLine}</span>
        </p>
        <ul className="lp-demo__tags">
          {DEMO_VERDICT.failureTypes.map((f) => (
            <li key={f} className="lp-demo__ftag">
              {f}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
