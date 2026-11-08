import { api } from "./client";
import { ApiError, call } from "./call";
import type { components } from "./schema";

export type PromptVersion = components["schemas"]["PromptVersionOut"];
export type PromptVersionCreate = components["schemas"]["PromptVersionCreate"];
export type PromptTool = components["schemas"]["PromptTool"];
export type Provider = PromptVersionCreate["provider"];

export const PROVIDERS: { value: Provider; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "groq", label: "Groq" },
  { value: "mistral", label: "Mistral" },
  { value: "ollama", label: "Ollama" },
  { value: "openai_compatible", label: "OpenAI-compatible" },
];

export const listPromptVersions = (agent_id: string) => call(api.GET("/api/v1/agents/{agent_id}/prompt-versions", { params: { path: { agent_id } } }));

export const getPromptVersion = (agent_id: string, version: number) =>
  call(api.GET("/api/v1/agents/{agent_id}/prompt-versions/{version}", { params: { path: { agent_id, version } } }));

export const activatePromptVersion = (agent_id: string, version: number) =>
  call(api.POST("/api/v1/agents/{agent_id}/prompt-versions/{version}/activate", { params: { path: { agent_id, version } } }));

/** 201 is a new version; 200 means the content matched the active version, which is returned unchanged. */
export async function createPromptVersion(agent_id: string, body: PromptVersionCreate): Promise<{ version: PromptVersion; created: boolean }> {
  const req = api.POST("/api/v1/agents/{agent_id}/prompt-versions", { params: { path: { agent_id } }, body });
  const version = await call(req);
  const { response } = await req;
  return { version, created: response.status === 201 };
}

/** The active version id lives in the agent's adapter config. */
export const activeVersionId = (agent: { adapter_config?: Record<string, unknown> }): string | null => {
  const v = agent.adapter_config?.active_version_id;
  return typeof v === "string" ? v : null;
};

const FRIENDLY: Record<string, string> = {
  base_url_not_allowed: "This base URL points at a private or internal address, which the server does not allow. Use the provider's public URL.",
  not_a_prompt_agent: "This agent is not a prompt agent, so it has no prompt versions.",
  prompt_agent_has_no_version: "This prompt agent has no saved version yet. Open the agent and save a prompt version first.",
};

/** Plain sentence for the prompt-agent error codes; other errors keep the API's own message. */
export function promptErrorMessage(e: unknown): string {
  if (e instanceof ApiError) return FRIENDLY[e.code] ?? e.userMessage();
  return "The request failed.";
}
