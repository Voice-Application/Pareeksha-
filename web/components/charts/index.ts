/**
 * Plain-SVG chart module. Small, documented client components built from inline SVG + the app's CSS
 * tokens — no charting library and no new npm deps. Single-series charts (LineChart, BarChart) use
 * the app accent hue; the categorical DonutChart uses the validated `--chart-cat-*` theme. Light/dark
 * palettes are driven by the app's `.dark` class via tokens, not by prefers-color-scheme. See each
 * component's doc comment for its form, interaction and accessibility contract.
 */

export { LineChart, type LinePoint } from "./line-chart";
export { BarChart, type Bar } from "./bar-chart";
export { DonutChart, type Slice } from "./donut-chart";
