"use client";

/**
 * Shared primitives for the plain-SVG chart module. Every chart in `components/charts/` is built
 * from inline SVG + the app's CSS tokens (no charting library, no new deps). These helpers keep the
 * marks, spacers, reduced-motion behaviour and the table-view fallback consistent across charts.
 *
 * Colour comes from tokens only: single-series charts use the accent hue (`var(--accent)`); the
 * categorical theme is `--chart-cat-1..4` (indigo/teal/violet/stone), set per mode in app/tokens.css. The
 * reserved verdict tokens (`--pass`/`--fail`/`--warn`) are used only for status meaning, never as a
 * categorical series.
 */

import { useEffect, useId, useState, type ReactNode } from "react";

/** The fixed categorical order — colour follows the entity, never its rank, and is never cycled.
 * The fourth slot is a neutral for grouped Other operations. */
export const CHART_CATEGORICAL = ["var(--chart-cat-1)", "var(--chart-cat-2)", "var(--chart-cat-3)", "var(--chart-cat-4)"] as const;

/** A measured-out plot box inside an SVG viewBox: the area where marks are drawn, minus the axes gutter. */
export type Plot = { x: number; y: number; w: number; h: number };

/** Linear interpolation from a data value in [min,max] to a pixel position in [lo,hi]. */
export function scaleLinear(value: number, min: number, max: number, lo: number, hi: number): number {
  if (max === min) return lo;
  return lo + ((value - min) / (max - min)) * (hi - lo);
}

/**
 * A visually-hidden <table> fallback so every charted value is reachable without hover or sight.
 * Rendered off-screen (the app's `sr-only` pattern) but in the accessibility tree.
 */
export function DataTable({ caption, columns, rows }: { caption: string; columns: string[]; rows: (string | number)[][] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c} scope="col">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((cell, j) => (
              <td key={j}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * A pointer/focus-driven tooltip positioned over the chart. `leftPct` is a 0–100 percentage of the
 * container width (so it tracks a width-100% SVG without reading its rendered pixel size), `top` is
 * a pixel offset from the top. Values lead, labels follow (interaction.md). Labels are passed as
 * React children (text nodes), never innerHTML, since series/category names are untrusted data.
 */
export function Tooltip({ leftPct, top, children }: { leftPct: number; top: number; children: ReactNode }) {
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-sm border border-border bg-surface px-2.5 py-1.5 text-xs shadow-[var(--shadow-float)]"
      style={{ left: `${leftPct}%`, top: top - 8 }}
    >
      {children}
    </div>
  );
}

/** A stable id scoped to one chart instance, for aria wiring and SVG defs. */
export function useChartId(prefix: string) {
  const id = useId();
  return `${prefix}-${id.replace(/:/g, "")}`;
}

/** Dismiss the active chart tooltip with Escape while keeping the current mark focused. */
export function useChartSelection() {
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => {
    if (active == null) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActive(null);
    };
    document.addEventListener("keydown", dismiss);
    return () => document.removeEventListener("keydown", dismiss);
  }, [active]);
  return [active, setActive] as const;
}
