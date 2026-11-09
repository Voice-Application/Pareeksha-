import { api } from "./client";
import { call } from "./call";
import type { components } from "./schema";

type S = components["schemas"];
export type QuickTest = S["QuickTestOut"];
export type QuickTestCreate = S["QuickTestCreate"];
export type QuickTestCreated = S["QuickTestCreated"];
export type QuickTestListItem = S["QuickTestListItem"];
export type QuickTestSetup = S["QuickTestSetup"];
export type QuickTestImprovement = S["QuickTestImprovement"];
export type RuleResult = S["RuleResult"];
export type Conversation = S["Conversation"];
export type CostEstimate = S["CostEstimate"];
export type AssistantRequest = S["AssistantRequest"];
export type AssistantResponse = S["AssistantResponse"];

export const getSetup = () => call(api.GET("/api/v1/quick-tests/setup"));
export const listQuickTests = () => call(api.GET("/api/v1/quick-tests"));
export const getQuickTest = (test_id: string) => call(api.GET("/api/v1/quick-tests/{test_id}", { params: { path: { test_id } } }));
/** 402 `confirm_cost` carries `details.estimate` and `details.plan`: send the body again with both. */
export const createQuickTest = (body: QuickTestCreate) => call(api.POST("/api/v1/quick-tests", { body }));
export const improveQuickTest = (test_id: string, instructions: string, retest: boolean) =>
  call(api.POST("/api/v1/quick-tests/{test_id}/improve", { params: { path: { test_id } }, body: { instructions, retest } }));
export const retestQuickTest = (test_id: string, confirm_cost = false) =>
  call(api.POST("/api/v1/quick-tests/{test_id}/retest", { params: { path: { test_id }, query: { confirm_cost } } }));
export const askAssistant = (body: AssistantRequest) => call(api.POST("/api/v1/assistant/chat", { body }));

/** Poll every 3 s until every conversation has ended and been checked. */
export const quickTestPoll = (status: QuickTest["status"] | undefined) => (status === "done" || status === "failed" ? false : 3000);

/** Like ``quickTestPoll``, but after `done` keeps reading (up to 60 reads) until every checked conversation has its score. */
export function quickTestRefetch(s: { data?: QuickTest; dataUpdateCount: number; error: unknown }): number | false {
  if (s.error) return false;
  const base = quickTestPoll(s.data?.status);
  if (base !== false) return base;
  const unscored = s.data?.status === "done" && s.data.conversations.some((c) => c.status === "done" && c.score == null);
  return unscored && s.dataUpdateCount < 60 ? 3000 : false;
}

/** The list as an array (an unexpected body counts as empty instead of crashing the page). */
export const asList = (data: unknown): QuickTestListItem[] => (Array.isArray(data) ? (data as QuickTestListItem[]) : []);
/** Poll the list every 4 s while any test in it is still running. */
export const listPoll = (data: unknown) => (asList(data).some((t) => t.status === "running" || t.status === "checking") ? 4000 : false);

/** A test's result in one sentence, for headings and cards. */
export function verdictLine(t: Pick<QuickTest, "status" | "progress" | "rules">): string {
  const broken = t.rules.filter((r) => r.status === "broken").length;
  if (t.status === "failed") return "The test could not run";
  if (t.status === "running") return `Testing: ${t.progress.finished} of ${t.progress.total} conversations done`;
  if (t.status === "checking") return `Checking the answers: ${t.progress.checked} of ${t.progress.total} done`;
  const untested = t.rules.filter((r) => r.status === "not_tested" || r.status === "pending").length;
  if (!broken && untested) return `Broke none of the ${t.rules.length - untested} rules checked; ${untested} could not be checked`;
  if (!broken) return `Kept all ${t.rules.length} rules`;
  return `Broke ${broken} of ${t.rules.length} rules`;
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const inr = (n: number | null | undefined) => (n == null ? "-" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
