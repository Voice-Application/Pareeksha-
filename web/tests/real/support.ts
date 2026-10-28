import { expect, type Page } from "@playwright/test";

export const API = process.env.REAL_API_URL ?? "http://127.0.0.1:8000/api/v1";
export const KEY = process.env.PAREEKSHA_API_KEY ?? "";
export const SHOTS = process.env.SHOT_DIR ?? "test-results/screens";

/** Direct API read from the test process (not the browser) to find real ids. */
export async function api<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${KEY}` } });
  expect(r.status, `GET ${path}`).toBe(200);
  return (await r.json()) as T;
}

/** Collects browser console errors and failed API calls for one page visit. */
export function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => {
    // "Failed to load resource" is the browser echoing a 404/5xx; 5xx are caught from the response event below
    // and a 404 is a legitimate empty state (e.g. no dialect report yet), so it is not a console failure here.
    if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) problems.push(`console: ${m.text().slice(0, 200)}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message.slice(0, 200)}`));
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 500) problems.push(`${r.status()} ${r.url()}`);
  });
  return problems;
}

export async function firstEvaluatedCall(): Promise<{ runId: string; callId: string }> {
  const runs = await api<{ items: { id: string }[] }>("/runs?limit=50");
  for (const run of runs.items) {
    const items = await api<{ items: { call_id: string | null; status: string }[] }>(`/runs/${run.id}/items?limit=50`);
    const hit = items.items.find((i) => i.call_id && i.status === "evaluated");
    if (hit) return { runId: run.id, callId: hit.call_id! };
  }
  throw new Error("no evaluated call in the stack: run the demo or a run first");
}
