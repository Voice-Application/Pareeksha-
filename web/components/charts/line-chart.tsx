"use client";

/**
 * LineChart — a single-series trend over an ordered sequence (e.g. mean score across runs).
 *
 * Form: change-over-time → a line. One y-axis only (dataviz non-negotiable). Single series, so the
 * stroke is the app accent (`var(--accent)`) and there is no legend box — the title names it. A
 * dashed reference line marks a threshold (the pass line at 80, labelled). Interaction: a crosshair
 * snaps to the nearest point and a tooltip reads value + label; the same shows on keyboard focus.
 * A visually-hidden table carries every value for non-visual/no-hover readers. Entrance motion is a
 * short line-draw, suppressed under prefers-reduced-motion by the global rule in globals.css.
 */

import { useState, type CSSProperties } from "react";
import { DataTable, Tooltip, scaleLinear, useChartId, type Plot } from "./shared";

export type LinePoint = { label: string; value: number };

export function LineChart({
  points,
  title,
  yMax = 100,
  yMin = 0,
  passLine,
  valueSuffix = "",
  height = 220,
}: {
  /** Ordered points, left→right; `label` is the x identity (run name/date), `value` the y measure. */
  points: LinePoint[];
  /** Accessible chart name (also the visible context lives in the surrounding Panel title). */
  title: string;
  yMax?: number;
  yMin?: number;
  /** Optional dashed reference line (e.g. 80), drawn + labelled when within [yMin,yMax]. */
  passLine?: number;
  valueSuffix?: string;
  height?: number;
}) {
  const id = useChartId("line");
  const [active, setActive] = useState<number | null>(null);

  const W = 640;
  const H = height;
  // Axis gutters: room for y ticks on the left and x labels at the bottom.
  const plot: Plot = { x: 44, y: 12, w: W - 44 - 12, h: H - 12 - 28 };
  const n = points.length;

  const px = (i: number) => (n <= 1 ? plot.x + plot.w / 2 : scaleLinear(i, 0, n - 1, plot.x, plot.x + plot.w));
  const py = (v: number) => scaleLinear(v, yMin, yMax, plot.y + plot.h, plot.y);

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p.value).toFixed(1)}`).join(" ");
  const yTicks = [yMin, (yMin + yMax) / 2, yMax];

  // Snap the crosshair to the nearest point by pointer x.
  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    // The hit rect spans only the plot box, so map into plot coordinates (the same space as px).
    const rx = plot.x + ((e.clientX - rect.left) / rect.width) * plot.w;
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const d = Math.abs(px(i) - rx);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    setActive(best);
  };

  // A refresh can shorten the series while a point is selected; treat an out-of-range index as no selection.
  const ap = active != null ? (points[active] ?? null) : null;
  // Tooltip position: x as a % of container width (SVG is width-100%), y scaled to the rendered height.
  const tipLeftPct = ap ? (px(active!) / W) * 100 : 0;
  const tipTop = ap ? (py(ap.value) / H) * height : 0;

  return (
    <figure className="m-0">
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          role="group"
          aria-labelledby={`${id}-title`}
          className="block overflow-visible"
          preserveAspectRatio="none"
        >
          <title id={`${id}-title`}>{title}</title>

          {/* y gridlines + ticks: hairline, recessive */}
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={plot.x} y1={py(t)} x2={plot.x + plot.w} y2={py(t)} stroke="var(--grid)" strokeWidth={1} />
              <text x={plot.x - 8} y={py(t)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="var(--fg-subtle)" className="num">
                {t}
              </text>
            </g>
          ))}

          {/* pass line: dashed reference + inline label */}
          {passLine != null && passLine >= yMin && passLine <= yMax && (
            <g aria-hidden>
              <line x1={plot.x} y1={py(passLine)} x2={plot.x + plot.w} y2={py(passLine)} stroke="var(--fg-muted)" strokeWidth={1} strokeDasharray="4 4" />
              <text x={plot.x + plot.w} y={py(passLine) - 5} textAnchor="end" fontSize={11} fill="var(--fg-muted)">
                pass {passLine}
              </text>
            </g>
          )}

          {/* x labels, thinned so they never collide */}
          {points.map((p, i) => {
            const every = Math.ceil(n / 6);
            if (i % every !== 0 && i !== n - 1) return null;
            return (
              <text key={i} x={px(i)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--fg-subtle)">
                {p.label.length > 10 ? `${p.label.slice(0, 9)}…` : p.label}
              </text>
            );
          })}

          {/* the series line: 2px accent, round join; a short draw-in entrance */}
          <path
            d={path}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            className="chart-line-draw"
            style={{ "--len": "1000" } as CSSProperties}
          />

          {/* end marker, 8px with a 2px surface ring so it stays legible */}
          {n > 0 && (
            <circle cx={px(n - 1)} cy={py(points[n - 1].value)} r={4} fill="var(--accent)" stroke="var(--bg-surface)" strokeWidth={2} />
          )}
          {/* end value, direct-labelled */}
          {n > 0 && (
            <text x={px(n - 1)} y={py(points[n - 1].value) - 10} textAnchor="end" fontSize={11} fill="var(--fg)" className="num">
              {points[n - 1].value}
              {valueSuffix}
            </text>
          )}

          {/* crosshair + active dot */}
          {ap && (
            <g aria-hidden>
              <line x1={px(active!)} y1={plot.y} x2={px(active!)} y2={plot.y + plot.h} stroke="var(--border-strong)" strokeWidth={1} />
              <circle cx={px(active!)} cy={py(ap.value)} r={4.5} fill="var(--accent)" stroke="var(--bg-surface)" strokeWidth={2} />
            </g>
          )}

          {/* full-plot hit layer for the crosshair; keyboard focus steps through points */}
          <rect
            x={plot.x}
            y={plot.y}
            width={plot.w}
            height={plot.h}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setActive(null)}
            tabIndex={0}
            role="slider"
            aria-label={`${title}. Use arrow keys to inspect points.`}
            aria-valuemin={0}
            aria-valuemax={n - 1}
            aria-valuenow={active ?? 0}
            aria-valuetext={ap ? `${ap.label}: ${ap.value}${valueSuffix}` : undefined}
            onFocus={() => setActive((a) => a ?? 0)}
            onBlur={() => setActive(null)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setActive(null);
              else if (e.key === "ArrowRight") setActive((a) => Math.min(n - 1, (a ?? -1) + 1));
              else if (e.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? n) - 1));
            }}
            className="outline-none"
          />
        </svg>

        {ap && (
          <Tooltip leftPct={tipLeftPct} top={tipTop}>
            <span className="num block font-semibold text-fg">
              {ap.value}
              {valueSuffix}
            </span>
            <span className="block text-muted">{ap.label}</span>
          </Tooltip>
        )}
      </div>

      <DataTable
        caption={title}
        columns={["Run", `Value${valueSuffix ? ` (${valueSuffix.trim()})` : ""}`]}
        rows={points.map((p) => [p.label, p.value])}
      />
    </figure>
  );
}
