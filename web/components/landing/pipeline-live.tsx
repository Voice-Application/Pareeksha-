"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight } from "lucide-react";

/** The workers one call passes through, with the topic each one emits (backend/pareeksha/events/topics.py). */
const STAGES = [
  { name: "Planner", line: "Turns the matrix into one event per call.", emits: "call.requested.v1" },
  { name: "Simulator", line: "Dials the bot and speaks as the caller.", emits: "call.completed.v1" },
  { name: "Evaluator", line: "The judge scores; fixed checks run beside it.", emits: "evaluation.completed.v1" },
  { name: "Finalizer", line: "Totals the calls into the run's verdict.", emits: "run.completed.v1" },
  { name: "Integrations", line: "Sends the scores to HubSpot and webhooks.", emits: "HubSpot note, webhook" },
];
const RETRY = ["retry.30s.v1", "retry.5m.v1", "dlq.v1"];
const STEP_MS = 1600;

/**
 * One event moving through the pipeline. Still until it is on screen, stopped off screen, paused on hover
 * and on focus (tracked separately), never moving under reduced motion, with a visible pause control.
 */
export function PipelineLive() {
  const [at, setAt] = useState(0);
  const [held, setHeld] = useState(false);
  const [seen, setSeen] = useState(false);
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [still, setStill] = useState(true);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setStill(reduce.matches);
    sync();
    reduce.addEventListener("change", sync);
    const io = new IntersectionObserver(([e]) => setSeen(e.isIntersecting), { threshold: 0.3 });
    if (root.current) io.observe(root.current);
    return () => { reduce.removeEventListener("change", sync); io.disconnect(); };
  }, []);

  const running = seen && !held && !hover && !focus && !still;
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setAt((n) => (n + 1) % STAGES.length), STEP_MS);
    return () => window.clearInterval(id);
  }, [running]);

  return (
    <div
      ref={root}
      className="lp-pipe"
      data-running={running ? "" : undefined}
      onPointerEnter={() => setHover(true)}
      onPointerLeave={() => setHover(false)}
      onFocus={() => setFocus(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocus(false); }}
    >
      <ol className="lp-stages" aria-label="Diagram of the call pipeline">
        {STAGES.map((s, i) => (
          <li key={s.name} className="lp-stages__item" data-active={i === at ? "" : undefined} data-done={i < at ? "" : undefined}>
            <button type="button" className="lp-stage" aria-pressed={i === at} onClick={() => { setAt(i); setHeld(true); }}>
              <span className="lp-stage__n num" aria-hidden>{i + 1}</span>
              <span className="lp-stage__name">{s.name}</span>
              <span className="lp-stage__line">{s.line}</span>
            </button>
            <p className="lp-stage__out">
              <span className="lp-stage__wire" aria-hidden><span /></span>
              <code>{s.emits}</code>
            </p>
          </li>
        ))}
      </ol>
      <div className="lp-pipe__foot">
        <p className="lp-pipe__retry">
          <span>A handler that throws</span>
          {RETRY.map((r, i) => (
            <span key={r} className="lp-pipe__hop">
              <ArrowRight size={14} strokeWidth={1.8} aria-hidden />
              <code data-last={i === RETRY.length - 1 ? "" : undefined}>{r}</code>
            </span>
          ))}
          <span className="sr-only">: retried after 30 seconds, then 5 minutes, then parked in the dead-letter queue.</span>
        </p>
        {!still && (
          <button type="button" className="btn btn--quiet lp-pipe__toggle" onClick={() => setHeld((h) => !h)}>
            {held ? "Play" : "Pause"}
          </button>
        )}
      </div>
    </div>
  );
}
