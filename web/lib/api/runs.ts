import { api } from "./client";
import { call } from "./call";
import type { operations } from "./schema";

/** Types are taken from the call results (not components["schemas"]) so tuple fields such as top_failure_types match what openapi-fetch returns. */
export const listRuns = (query: NonNullable<operations["list_runs"]["parameters"]["query"]>) => call(api.GET("/api/v1/runs", { params: { query } }));
export const getRun = (run_id: string) => call(api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id } } }));
export const listRunItems = (run_id: string, cursor?: string | null) =>
  call(api.GET("/api/v1/runs/{run_id}/items", { params: { path: { run_id }, query: { limit: 200, cursor } } }));

export type Run = Awaited<ReturnType<typeof getRun>>;
export type RunItem = Awaited<ReturnType<typeof listRunItems>>["items"][number];
export type RunSummary = NonNullable<Run["summary"]>;
