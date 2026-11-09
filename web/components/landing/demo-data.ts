/**
 * Sample data for the landing-page demos. Mirrors real shapes and values pulled from a seeded
 * "planted-bugs" run (a gold-loan call the bot fails by hallucinating a rate), so the scripted hero
 * demo and the feature tabs stay honest without calling the backend. Not live data — illustration only.
 */

export type DemoTurn = { speaker: "caller" | "agent"; text: string; broke?: string };

/** The scripted conversation the hero plays out, turn by turn. */
export const DEMO_TURNS: DemoTurn[] = [
  { speaker: "caller", text: "Do you offer gold loans?" },
  {
    speaker: "agent",
    text: "Yes, we offer gold loans at 9.5% interest with same-day disbursal.",
    broke: "Stated a rate and a turnaround that are nowhere in the documents.",
  },
];

/** The system prompt the hero shows being pasted (short, representative). */
export const DEMO_PROMPT =
  "You are the support line for a bank. Answer only from the provided documents. Never invent rates, fees or timelines. If you don't know, say so and offer to connect a human.";

/** The verdict the demo lands on — real numbers from the seeded call. */
export const DEMO_VERDICT = {
  score: 57.5,
  passLine: 80,
  passed: false,
  critical: true,
  failureTypes: ["hallucination", "wrong_fact"] as const,
  rubric: "rubric-2026-11-v3",
};

/** Rubric dimensions (0-5), as the judge scored this call. */
export const DEMO_DIMENSIONS: { key: string; label: string; score: number }[] = [
  { key: "task_completion", label: "Task completion", score: 0 },
  { key: "factual_accuracy", label: "Factual accuracy", score: 0 },
  { key: "policy_compliance", label: "Policy compliance", score: 4 },
  { key: "escalation", label: "Escalation", score: 4 },
  { key: "conversation_flow", label: "Conversation flow", score: 4 },
  { key: "language_handling", label: "Language handling", score: 4 },
  { key: "empathy_tone", label: "Empathy & tone", score: 3 },
];

/** RAG lab: real retrieval setups from the seeded matrix, best last. */
export const DEMO_RAG: { setup: string; passRate: number; scoreMean: number }[] = [
  { setup: "bm25 · e5-large · k3", passRate: 0.71, scoreMean: 89.55 },
  { setup: "hybrid · e5-large · k3", passRate: 0.93, scoreMean: 95.18 },
  { setup: "hybrid + rerank · e5-large", passRate: 1.0, scoreMean: 97.5 },
];

/**
 * Dialect gap: illustrative ASR word-error-rate per dialect/line. Representative sample, not a
 * seeded report — labelled as such in the UI.
 */
export const DEMO_DIALECT: { dialect: string; wer: number; n: number }[] = [
  { dialect: "Hindi · clean line", wer: 0.06, n: 120 },
  { dialect: "Hindi · mobile, noisy", wer: 0.14, n: 118 },
  { dialect: "Kannada · clean line", wer: 0.11, n: 96 },
  { dialect: "Kannada · mobile, noisy", wer: 0.23, n: 94 },
  { dialect: "Tamil · code-mixed", wer: 0.19, n: 88 },
];
