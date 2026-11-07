import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type Draft = S["DesignerDraft"];
export type DraftAgent = S["DraftAgent"];
export type Question = S["DesignerQuestion"];
export type ChatTurn = S["ChatTurn"];

/** One line of the log. Assistant questions are kept apart from the reply so they render as a list; they are folded back into the text sent to the API. */
export type Entry = {
  role: ChatTurn["role"];
  content: string;
  questions?: Question[];
};

/** The commit result plus what the success line names. */
export type Committed = S["DesignerCommitResult"] & {
  agent_name: string;
  new_personas: number;
};

/** What survives a reload (sessionStorage). Never holds a key or anything beyond what the user typed and the API returned. */
export type Saved = {
  log: Entry[];
  draft: Draft | null;
  ready: boolean;
  committed: Committed | null;
};

/** The API is stateless: every turn sends the whole history. */
export function toTurns(log: Entry[]): ChatTurn[] {
  return log.map((e) => ({
    role: e.role,
    content: e.questions?.length
      ? `${e.content}\n\n${e.questions.map((q, i) => `${i + 1}. ${q.text}${q.options?.length ? ` (${q.options.join(" / ")})` : ""}`).join("\n")}`
      : e.content,
  }));
}

/** Per message limit from docs/06-api-spec.md section 14. */
export const MAX_MESSAGE_CHARS = 20_000;

/** Request limits from the same section: at most 40 messages, 60,000 characters in total. */
export const MAX_MESSAGES = 40;
export const MAX_TOTAL_CHARS = 60_000;
