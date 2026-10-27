import type { Step } from "@/components/ui/measure";

/** Metric to score-scale step (docs/design/pages/12-dialect.md). WER and CER: lower is better; entity accuracy: higher is better. All values are fractions 0-1. */
export type Metric = "wer" | "cer" | "entity_acc";

export const METRIC_LABEL: Record<Metric, string> = { wer: "WER", cer: "CER", entity_acc: "Entity accuracy" };
export const METRIC_NOTE: Record<Metric, string> = { wer: "Lower is better", cer: "Lower is better", entity_acc: "Higher is better" };

const LOWER: Record<"wer" | "cer", number[]> = { wer: [0.1, 0.2, 0.3, 0.45], cer: [0.05, 0.1, 0.15, 0.25] };
const HIGHER = [0.9, 0.8, 0.7, 0.55];

export function metricStep(metric: Metric, v: number): Step {
  if (metric === "entity_acc") return v >= HIGHER[0] ? 5 : v >= HIGHER[1] ? 4 : v >= HIGHER[2] ? 3 : v >= HIGHER[3] ? 2 : 1;
  const t = LOWER[metric];
  return v < t[0] ? 5 : v < t[1] ? 4 : v < t[2] ? 3 : v < t[3] ? 2 : 1;
}
/** Legend rows worst to best. */
export function metricLegend(metric: Metric): [Step, string][] {
  if (metric === "entity_acc") return [[1, "below 55%"], [2, "55-69%"], [3, "70-79%"], [4, "80-89%"], [5, "90%+"]];
  const t = LOWER[metric].map((x) => Math.round(x * 100));
  return [[1, `${t[3]}%+`], [2, `${t[2]}-${t[3] - 1}%`], [3, `${t[1]}-${t[2] - 1}%`], [4, `${t[0]}-${t[1] - 1}%`], [5, `below ${t[0]}%`]];
}
export const LOW_N = 10;
export const CONDITION_ORDER = ["clean_16k", "pstn_8k_alaw", "pstn_street_10db"];
