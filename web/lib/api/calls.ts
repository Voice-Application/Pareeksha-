import { api } from "./client";
import { call } from "./call";

export const getCall = (call_id: string) => call(api.GET("/api/v1/calls/{call_id}", { params: { path: { call_id } } }));
export type CallDetailData = Awaited<ReturnType<typeof getCall>>;
export type Turn = NonNullable<CallDetailData["turns"]>[number];
export type CallEvaluation = NonNullable<CallDetailData["evaluation"]>;
export type CheckRow = NonNullable<CallDetailData["checks"]>[number];

export const audioUrl = (callId: string, track: "mixed" | "caller" | "agent" | "original") => `/api/proxy/api/v1/calls/${callId}/audio/${track}`;

/** Rubric (docs/08): dimension order and weights. A score of 0 on a critical dimension is a critical failure. */
export const RUBRIC: { key: string; label: string; weight: number; critical: boolean }[] = [
  { key: "task_completion", label: "Task completion", weight: 25, critical: false },
  { key: "policy_compliance", label: "Policy compliance", weight: 20, critical: true },
  { key: "factual_accuracy", label: "Factual accuracy", weight: 15, critical: true },
  { key: "language_handling", label: "Language handling", weight: 15, critical: false },
  { key: "conversation_flow", label: "Conversation flow", weight: 10, critical: false },
  { key: "empathy_tone", label: "Empathy and tone", weight: 10, critical: true },
  { key: "escalation", label: "Escalation", weight: 5, critical: true },
];

/** The API gives failure tags per call, not per turn. A tag points at the turns of the check that raised it, else of the dimension it belongs to. */
export const TAG_DIMENSION: Record<string, string> = {
  intent_miss: "task_completion",
  tool_selection: "task_completion",
  tool_arguments: "task_completion",
  wrong_fact: "factual_accuracy",
  hallucination: "factual_accuracy",
  asr_misrecognition: "factual_accuracy",
  missing_disclosure: "policy_compliance",
  policy_violation: "policy_compliance",
  prompt_injection: "policy_compliance",
  language_mismatch: "language_handling",
  latency: "conversation_flow",
  interruption_handling: "conversation_flow",
  loop: "conversation_flow",
  escalation_error: "escalation",
};
export const CHECK_TAG: Record<string, string> = {
  disclosure_present: "missing_disclosure",
  forbidden_absent: "policy_violation",
  language_match: "language_mismatch",
  no_loop: "loop",
  amount_confirmed: "wrong_fact",
  tool_calls_expected: "tool_selection",
};

export function mmss(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
