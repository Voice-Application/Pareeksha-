import type { RunItem } from "@/lib/api/runs";
import { RUBRIC } from "@/lib/api/calls";

export const cellKey = (scenario: string, persona: string, profile: string) => `${scenario}\u0000${persona}\u0000${profile}`;

export type Compared = { scenario: string; persona: string; profile: string; base_score?: number | null; head_score?: number | null; delta?: number | null; newly_failing: boolean };
export type Group = "newly" | "regressed" | "improved" | "unchanged" | "partial";

export function groupOf(c: Compared): Group {
  if (c.delta == null) return "partial";
  if (c.newly_failing) return "newly";
  return c.delta < 0 ? "regressed" : c.delta > 0 ? "improved" : "unchanged";
}

const ORDER: Record<Group, number> = { newly: 0, regressed: 1, improved: 2, unchanged: 3, partial: 4 };
/** Newly failing, then regressed by delta ascending, then improved (largest gain first), then unchanged, then cells only one run scored. */
export function sortCells<T extends Compared>(cells: T[]): T[] {
  return [...cells].sort((a, b) => {
    const ga = ORDER[groupOf(a)];
    const gb = ORDER[groupOf(b)];
    if (ga !== gb) return ga - gb;
    const da = a.delta ?? 0;
    const db = b.delta ?? 0;
    return (groupOf(a) === "improved" ? db - da : da - db) || cellKey(a.scenario, a.persona, a.profile).localeCompare(cellKey(b.scenario, b.persona, b.profile));
  });
}

/** call id per matrix cell: the worst-scored evaluated item (what the cell score is drawn from), else any item with a call. */
export function callByCell(items: RunItem[] | undefined): Map<string, string> {
  const out = new Map<string, RunItem>();
  for (const i of items ?? []) {
    if (!i.call_id) continue;
    const k = cellKey(i.scenario, i.persona, i.noise_profile);
    const cur = out.get(k);
    if (!cur || (i.overall_score ?? 101) < (cur.overall_score ?? 101)) out.set(k, i);
  }
  return new Map([...out].map(([k, v]) => [k, v.call_id as string]));
}

export type DimMeans = Record<string, number | undefined>;
/** Mean 0-4 score per rubric dimension across the evaluations given. */
export function dimensionMeans(evals: { dimensions?: Record<string, { score: number }> }[]): DimMeans {
  const out: DimMeans = {};
  for (const d of RUBRIC) {
    const xs = evals.map((e) => e.dimensions?.[d.key]?.score).filter((x): x is number => typeof x === "number");
    out[d.key] = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : undefined;
  }
  return out;
}

export type Line = { text: string; kind: "added" | "removed" };
/** Added/removed entries between two lists of strings. */
export function listDiff(base: string[], head: string[]): Line[] {
  const b = new Set(base);
  const h = new Set(head);
  return [...base.filter((x) => !h.has(x)).map((text) => ({ text, kind: "removed" as const })), ...head.filter((x) => !b.has(x)).map((text) => ({ text, kind: "added" as const }))];
}
