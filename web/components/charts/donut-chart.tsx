"use client";

/**
 * DonutChart — composition of one whole across a small, fixed set of categories (e.g. token usage by
 * operation: llm_caller / llm_designer / llm_judge). Form: part-of-a-whole with few slices → a donut.
 * Colour is categorical and assigned in the fixed theme order (`--chart-cat-1..4`), per entity and
 * never cycled; the reserved verdict hues are never used here. Identity is never colour-alone: a
 * legend is always present AND (≤ 4 slices) each slice is direct-labelled with its name + share.
 * Each arc is its own hit target with a per-arc tooltip. A visually-hidden table carries raw units.
 * The center prints the total as a quiet hero. Entrance is suppressed under prefers-reduced-motion.
 */

import { CHART_CATEGORICAL, DataTable, Tooltip, useChartSelection, useChartId } from "./shared";

export type Slice = { label: string; value: number; colorIndex?: number; color?: string };

/** Explicit entity colors take priority; otherwise use the stable slot, never cycle the palette. */
const sliceColor = (slice: Slice, index: number) => slice.color ?? CHART_CATEGORICAL[Math.min(slice.colorIndex ?? index, CHART_CATEGORICAL.length - 1)];

/** Point on a circle at `deg` degrees (0 = 12 o'clock, clockwise), radius `r`, centered at (cx,cy). */
function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/** SVG arc path for a donut segment from `a0` to `a1` degrees, between inner and outer radius. */
function arcPath(cx: number, cy: number, rOuter: number, rInner: number, a0: number, a1: number) {
  const large = a1 - a0 > 180 ? 1 : 0;
  const o0 = polar(cx, cy, rOuter, a0);
  const o1 = polar(cx, cy, rOuter, a1);
  const i1 = polar(cx, cy, rInner, a1);
  const i0 = polar(cx, cy, rInner, a0);
  return `M${o0.x},${o0.y} A${rOuter},${rOuter} 0 ${large} 1 ${o1.x},${o1.y} L${i1.x},${i1.y} A${rInner},${rInner} 0 ${large} 0 ${i0.x},${i0.y} Z`;
}

export function DonutChart({
  slices,
  title,
  centerLabel,
  unitLabel = "units",
}: {
  /** Categories may supply a stable colorIndex to preserve identity when filtered or reordered. */
  slices: Slice[];
  /** Accessible chart name; visible context lives in the surrounding Panel title. */
  title: string;
  /** Short label under the center total (e.g. "tokens"). */
  centerLabel?: string;
  unitLabel?: string;
}) {
  const id = useChartId("donut");
  const [active, setActive] = useChartSelection();

  const total = slices.reduce((s, x) => s + x.value, 0);
  const W = 260;
  const H = 240;
  const cx = 130;
  const cy = 120;
  const rOuter = 92;
  const rInner = 58;
  const GAP = 2.2; // degrees of surface gap between neighbouring arcs

  // Build cumulative angles without mutating a closure variable; a zero-value slice draws nothing.
  const segs = slices.reduce<{ label: string; value: number; i: number; frac: number; a0: number; a1: number; colorIndex: number }[]>((acc, s, i) => {
    const frac = total > 0 ? s.value / total : 0;
    const a0 = acc.length ? acc[acc.length - 1].a1 : 0;
    acc.push({ colorIndex: s.colorIndex ?? i, label: s.label, value: s.value, i, frac, a0, a1: a0 + frac * 360 });
    return acc;
  }, []);

  const fmt = (n: number) => n.toLocaleString("en-US");

  return (
    <figure className="m-0 flex flex-col gap-4 min-[420px]:flex-row min-[420px]:items-center">
      <div className="relative shrink-0">
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="group" aria-labelledby={`${id}-title`} className="block max-w-full">
          <title id={`${id}-title`}>{title}</title>
          {segs.map((s) => {
            if (s.frac <= 0) return null;
            // Keep at least 70% of even the narrowest segment visible.
            const gap = Math.min(GAP, (s.a1 - s.a0) * 0.3);
            return (
              <g
                key={s.i}
                tabIndex={0}
                role="button"
                aria-label={`${s.label}: ${fmt(s.value)} ${unitLabel}, ${Math.round(s.frac * 100)}%`}
                onPointerEnter={() => setActive(s.i)}
                onPointerLeave={() => setActive((a) => (a === s.i ? null : a))}
                onFocus={() => setActive(s.i)}
                onBlur={() => setActive((a) => (a === s.i ? null : a))}
                className="outline-none"
              >
                <path
                  d={arcPath(cx, cy, rOuter, rInner, s.a0 + gap / 2, s.a1 - gap / 2)}
                  fill={sliceColor(slices[s.i], s.i)}
                  opacity={active == null || active === s.i ? 1 : 0.45}
                  className="chart-arc-in"
                  style={{ transformBox: "fill-box", transformOrigin: "center" }}
                />
                {/* Cover the untrimmed arc, with a minimum target for very narrow slices. */}
                <path d={arcPath(cx, cy, rOuter, rInner, s.a0, s.a1)} fill="transparent" />
              </g>
            );
          })}
          {/* Narrow-slice targets sit above every arc so neighbours cannot cover them. */}
          {segs.filter((s) => s.frac > 0 && s.a1 - s.a0 < 12).map((s) => {
            const target = polar(cx, cy, (rOuter + rInner) / 2, (s.a0 + s.a1) / 2);
            return <circle key={s.i} cx={target.x} cy={target.y} r={10} fill="transparent" aria-hidden
              onPointerEnter={() => setActive(s.i)}
              onPointerLeave={() => setActive((a) => a === s.i ? null : a)} />;
          })}
          {/* center: total as a quiet hero */}
          <text x={cx} y={cy - 2} textAnchor="middle" dominantBaseline="middle" fontSize={22} fontWeight={600} fill="var(--fg)" className="num">
            {total >= 1000 ? `${(total / 1000).toFixed(total >= 10000 ? 0 : 1)}K` : fmt(total)}
          </text>
          {centerLabel && (
            <text x={cx} y={cy + 18} textAnchor="middle" dominantBaseline="middle" fontSize={11} fill="var(--fg-subtle)">
              {centerLabel}
            </text>
          )}
        </svg>

        {active != null && slices[active] && (
          <Tooltip leftPct={(cx / W) * 100} top={cy - rOuter}>
            <span className="num block font-semibold text-fg">{fmt(slices[active].value)}</span>
            <span className="block text-muted">
              {slices[active].label} · {Math.round(segs[active].frac * 100)}%
            </span>
          </Tooltip>
        )}
      </div>

      {/* legend (always present for ≥ 2 series) + direct name/share labels (≤ 4 slices) */}
      <ul className="flex min-w-0 flex-col gap-2 text-sm">
        {segs.map((s) => (
          <li key={s.i} className="flex min-w-0 items-center gap-2.5">
            <span className="h-2.5 w-2.5 shrink-0 rounded-xs" style={{ background: sliceColor(slices[s.i], s.i) }} aria-hidden />
            <span className="min-w-0 flex-1 truncate text-muted">{s.label}</span>
            <span className="num shrink-0 tabular-nums text-fg">{Math.round(s.frac * 100)}%</span>
          </li>
        ))}
      </ul>

      <DataTable
        caption={title}
        columns={["Operation", unitLabel.charAt(0).toUpperCase() + unitLabel.slice(1), "Share"]}
        rows={slices.map((s, i) => [s.label, s.value, `${Math.round((segs[i]?.frac ?? 0) * 100)}%`])}
      />
    </figure>
  );
}
