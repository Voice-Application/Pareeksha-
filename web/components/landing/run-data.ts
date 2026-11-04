/**
 * The planted-bugs run (9856641b), exported from the API on 2026-11-04: 3 scenarios, 3 callers, 2 lines,
 * against the bundled mock EMI bot. Listed in the order the calls finished, which is the order the replay uses.
 */
export type RunCall = {
  scenario: string;
  caller: "Kiran" | "Manju" | "Sunita";
  line: "pstn_8k_alaw" | "pstn_office_babble_15db";
  score: number;
  critical: boolean;
  passed: boolean;
  ms: number;
  tags: string[];
};

export const SCENARIOS = ["Asks for a human", "Disputes the EMI amount", "Promise to pay on Friday"] as const;
export const CALLERS = ["Kiran", "Manju", "Sunita"] as const;
export const CALLER_ROLE: Record<RunCall["caller"], string> = { Kiran: "IT employee", Manju: "auto driver", Sunita: "worried borrower" };
export const LINES = [
  { id: "pstn_8k_alaw", label: "Phone line" },
  { id: "pstn_office_babble_15db", label: "Office babble" },
] as const;

const c = (scenario: string, caller: RunCall["caller"], line: RunCall["line"], score: number, critical: boolean, ms: number, tags: string): RunCall => ({
  scenario,
  caller,
  line,
  score,
  critical,
  passed: false,
  ms,
  tags: tags.split(","),
});

const H = "Asks for a human", D = "Disputes the EMI amount", P = "Promise to pay on Friday";
const L8 = "pstn_8k_alaw" as const, LB = "pstn_office_babble_15db" as const;

export const RUN_CALLS: RunCall[] = [
  c(H, "Manju", L8, 13.75, true, 37986, "intent_miss,missing_disclosure,wrong_fact,language_mismatch,loop,escalation_error,tool_selection"),
  c(H, "Sunita", L8, 85, false, 21588, "missing_disclosure"),
  c(D, "Manju", LB, 15, true, 57770, "asr_misrecognition,missing_disclosure,language_mismatch,wrong_fact,tool_arguments,interruption_handling"),
  c(H, "Sunita", LB, 85, false, 21773, "missing_disclosure"),
  c(D, "Kiran", L8, 15, true, 48730, "wrong_fact,missing_disclosure,language_mismatch,interruption_handling,loop,escalation_error"),
  c(H, "Kiran", LB, 13.75, true, 36309, "intent_miss,missing_disclosure,wrong_fact,language_mismatch,escalation_error,tool_selection"),
  c(D, "Sunita", L8, 26.25, true, 129940, "loop,missing_disclosure,wrong_fact,tool_arguments,escalation_error"),
  c(D, "Kiran", LB, 25, false, 55639, "missing_disclosure,intent_miss,language_mismatch"),
  c(P, "Kiran", LB, 43.75, false, 25375, "missing_disclosure,language_mismatch,interruption_handling,wrong_fact"),
  c(D, "Manju", L8, 15, true, 64830, "missing_disclosure,language_mismatch,wrong_fact,tool_arguments,interruption_handling,escalation_error"),
  c(P, "Sunita", LB, 45, false, 21895, "missing_disclosure,intent_miss,wrong_fact"),
  c(P, "Manju", LB, 33.75, true, 46590, "missing_disclosure,language_mismatch,loop,interruption_handling,intent_miss,wrong_fact"),
  c(H, "Kiran", L8, 13.75, true, 43279, "intent_miss,missing_disclosure,language_mismatch,loop,escalation_error,hallucination,tool_selection,wrong_fact"),
  c(D, "Sunita", LB, 28.75, true, 43362, "wrong_fact,missing_disclosure,tool_arguments,intent_miss"),
  c(P, "Sunita", L8, 42.5, true, 23502, "missing_disclosure,intent_miss,wrong_fact"),
  c(P, "Kiran", L8, 43.75, false, 55554, "missing_disclosure,language_mismatch,interruption_handling,wrong_fact"),
  c(P, "Manju", L8, 31.25, true, 28207, "missing_disclosure,language_mismatch,intent_miss,interruption_handling,wrong_fact"),
  c(H, "Manju", LB, 13.75, true, 55508, "intent_miss,missing_disclosure,language_mismatch,escalation_error,tool_selection,tool_arguments,wrong_fact"),
];
