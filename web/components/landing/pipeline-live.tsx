"use client";

import { useEffect, useRef, useState } from "react";

/** The workers one call passes through, with the topic each one emits (backend/pareeksha/events/topics.py). */
const STAGES = [
  { name: "Planner", line: "Turns the matrix into calls.", emits: "call.requested.v1" },
  { name: "Simulator", line: "Speaks as the caller.", emits: "call.completed.v1" },
  { name: "Evaluator", line: "The judge scores the call.", emits: "evaluation.completed.v1" },
  { name: "Finalizer", line: "Totals the run into a verdict.", emits: "run.completed.v1" },
  { name: "Integrations", line: "Sends the scores on.", emits: "HubSpot, webhooks" },
];
const STEP_MS = 1600;

/**
 * One event moving through the pipeline. Still until it is on screen, stopped off screen,
 * paused on hover and focus, never moving under reduced motion, with a visible pause control.
 */
export function PipelineLive() {
  const [at, setAt] = useState(0);
  const [held, setHeld] = useState(false);
  const [seen, setSeen] = useState(false);
  const [over, setOver] = useState(false);
  const [focused, setFocused] = useState(false);
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

  const running = seen && !held && !over && !focused && !still;
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
      onPointerEnter={() => setOver(true)}
      onPointerLeave={() => setOver(false)}
      onFocus={() => setFocused(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false); }}
      style={{ "--at": at } as React.CSSProperties}
    >
      <ol className="lp-flow" aria-label="Diagram of the call pipeline">
        {STAGES.map((s, i) => (
          <li key={s.name} data-active={i === at ? "" : undefined}>
            <button type="button" className="lp-flow__node" aria-pressed={i === at} onClick={() => { setAt(i); setHeld(true); }}>
              <span className="sr-only">Show step {i + 1}, </span>{s.name}
            </button>
            <p>{s.line}</p>
            <p className="lp-flow__emit"><code>{s.emits}</code></p>
          </li>
        ))}
      </ol>
      {!still && (
        <button type="button" className="btn btn--quiet lp-pipe__toggle" onClick={() => setHeld((h) => !h)}>
          {held ? "Play" : "Pause"}
        </button>
      )}
    </div>
  );
}
