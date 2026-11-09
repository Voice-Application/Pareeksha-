"use client";

/**
 * BarChart — a single-series magnitude comparison across categories (e.g. pass-rate per run, or per
 * retrieval setup). Columns grow from one baseline; one y-axis only. Single series → accent fill,
 * no legend box. Each column is capped at 24px, has a 4px rounded cap and a squared base, and the
 * slot is kept wider than the bar so neighbours read apart on surface air (the 2px gap, and then
 * some). Each bar is its own hit target: hover/focus lifts it and shows a per-bar tooltip; the value
 * is also direct-labelled on the cap and kept in the visually-hidden table. Entrance grow is
 * suppressed under prefers-reduced-motion by the global rule in globals.css.
 */

import { type CSSProperties } from "react";
import { DataTable, Tooltip, useChartSelection, scaleLinear, useChartId, type Plot } from "./shared";

export type Bar = { label: string; value: number };

export function BarChart({
  bars,
  title,
  yMax = 100,
  valueSuffix = "%",
  height = 220,
}: {
  bars: Bar[];
  /** Accessible chart name; the visible context lives in the surrounding Panel title. */
  title: string;
  yMax?: number;
  valueSuffix?: string;
  height?: number;
}) {
  const id = useChartId("bar");
  const [active, setActive] = useChartSelection();

  const W = 640;
  const H = height;
  const plot: Plot = { x: 44, y: 14, w: W - 44 - 12, h: H - 14 - 28 };
  const n = bars.length;

  const slot = plot.w / Math.max(1, n);
  // Cap thickness and never fill the slot: the leftover slot width is the air (>= 2px gap) between bars.
  const barW = Math.max(8, Math.min(24, slot - 12));
  const baseY = plot.y + plot.h;
  const bx = (i: number) => plot.x + i * slot + (slot - barW) / 2;
  const bh = (v: number) => baseY - scaleLinear(v, 0, yMax, baseY, plot.y);

  const yTicks = [0, yMax / 2, yMax];

  const ab = active != null ? bars[active] : null;
  const tipLeftPct = ab && active != null ? ((bx(active) + barW / 2) / W) * 100 : 0;
  const tipTop = ab ? ((baseY - Math.max(0, bh(ab.value))) / H) * height : 0;

  return (
    <figure className="m-0">
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="group" aria-labelledby={`${id}-title`} className="block overflow-visible" preserveAspectRatio="none">
          <title id={`${id}-title`}>{title}</title>

          {yTicks.map((t) => (
            <g key={t}>
              <line x1={plot.x} y1={baseY - (t / yMax) * plot.h} x2={plot.x + plot.w} y2={baseY - (t / yMax) * plot.h} stroke="var(--grid)" strokeWidth={1} />
              <text x={plot.x - 8} y={baseY - (t / yMax) * plot.h} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="var(--fg-subtle)" className="num">
                {t}
              </text>
            </g>
          ))}

          {bars.map((b, i) => {
            const h = Math.max(0, bh(b.value));
            const x = bx(i);
            const y = baseY - h;
            const on = active === i;
            const grow = { transformOrigin: `${x + barW / 2}px ${baseY}px`, "--delay": `${i * 40}ms` } as CSSProperties;
            // The focusable bar holds only shapes; its value and axis label sit beside it so the
            // accessible name ("label: value") is not contradicted by truncated visible text.
            return (
              <g key={i}>
                <g
                  tabIndex={0}
                  role="button"
                  aria-label={`${b.label}: ${b.value}${valueSuffix}`}
                  onPointerEnter={() => setActive(i)}
                  onPointerLeave={() => setActive((a) => (a === i ? null : a))}
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive((a) => (a === i ? null : a))}
                  className="outline-none"
                >
                  {/* widened transparent hit target over the whole slot */}
                  <rect x={plot.x + i * slot} y={plot.y} width={slot} height={plot.h} fill="transparent" />
                  {/* the column: 4px rounded cap */}
                  <rect x={x} y={y} width={barW} height={h} rx={4} fill="var(--accent)" opacity={on ? 1 : 0.9} className="chart-bar-grow" style={grow} />
                  {/* square the base: fill the rounded bottom corners back in */}
                  {h > 4 && <rect x={x} y={baseY - 4} width={barW} height={4} fill="var(--accent)" opacity={on ? 1 : 0.9} className="chart-bar-grow" style={grow} />}
                </g>
                {/* value on the cap */}
                <text x={x + barW / 2} y={y - 6} textAnchor="middle" fontSize={11} fill="var(--fg)" className="num">
                  {b.value}
                  {valueSuffix}
                </text>
                {/* x label */}
                <text x={x + barW / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--fg-subtle)">
                  {b.label.length > 12 ? `${b.label.slice(0, 11)}…` : b.label}
                </text>
              </g>
            );
          })}
        </svg>

        {ab && (
          <Tooltip leftPct={tipLeftPct} top={tipTop}>
            <span className="num block font-semibold text-fg">
              {ab.value}
              {valueSuffix}
            </span>
            <span className="block text-muted">{ab.label}</span>
          </Tooltip>
        )}
      </div>

      <DataTable caption={title} columns={["Category", `Value${valueSuffix ? ` (${valueSuffix})` : ""}`]} rows={bars.map((b) => [b.label, b.value])} />
    </figure>
  );
}
