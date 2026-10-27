import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockFe, opsState, CALL_ID } from "./support/fe03-mock";
import { uuid } from "./support/mock-api";

async function axeClean(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes[0]?.target} ${v.nodes[0]?.html?.slice(0, 140)}`)).toEqual([]);
}
const page_ = (items: unknown[]) => ({ items, next_cursor: null });
const ts = "2026-10-24T10:00:00Z";

test.describe("DLQ", () => {
  test("lists the open event, shows error and envelope, replay moves it out of the open view", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/dlq");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("1 event is waiting in the dead-letter queue");
    await expect(page.getByRole("table", { name: "Dead-letter events" })).toContainText("pareeksha.call.completed.v1");
    await axeClean(page);
    await page.getByRole("button", { name: "pareeksha.call.completed.v1" }).click();
    await expect(page.getByLabel("envelope JSON", { exact: true })).toContainText("call.completed");
    await expect(page.getByLabel("error", { exact: true })).toContainText("JudgeSchemaError");
    await page.getByRole("button", { name: "Replay", exact: true }).click();
    await expect(page.getByText("Replayed. It will be processed again with attempt 1.")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("The dead-letter queue is empty");
  });

  test("discard asks for confirmation naming the consequence", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/dlq");
    await page.getByRole("button", { name: "pareeksha.call.completed.v1" }).click();
    await page.getByRole("button", { name: "Discard", exact: true }).click();
    await expect(page.getByText("Discard permanently? The event will not be processed.")).toBeVisible();
  });

  test("healthy empty state", async ({ page }) => {
    const st = opsState();
    st.dlq = [];
    await mockFe(page, st);
    await page.goto("/dlq");
    await expect(page.getByText("Events that fail three times will appear here.")).toBeVisible();
  });
});

test.describe("API keys", () => {
  test("a new key is shown once, in the dialog only, and is gone after Done", async ({ page }) => {
    const st = opsState();
    await mockFe(page, st);
    await page.goto("/settings/api-keys");
    await expect(page.getByRole("table", { name: "API keys" })).toContainText("pk_live_AaJPXAkX");
    await expect(page.getByText("pk_live_Zz9Yy8Xx_SECRET_SHOWN_ONCE")).toHaveCount(0);
    await page.getByRole("button", { name: "Create key" }).first().click();
    await page.getByLabel("Name", { exact: true }).fill("github-actions");
    await page.getByRole("checkbox", { name: /^runs:write / }).check();
    await page.getByRole("dialog").getByRole("button", { name: "Create key" }).click();
    await expect(page.getByLabel("New API key")).toHaveValue("pk_live_Zz9Yy8Xx_SECRET_SHOWN_ONCE");
    await expect(page.getByText("This is the only time you will see this key.")).toBeVisible();
    const done = page.getByRole("button", { name: "Done" });
    await expect(done).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(page.getByLabel("New API key")).toBeVisible(); // Esc does not close the reveal
    await page.getByLabel("I have copied the key").check();
    await done.click();
    await expect(page.getByText("pk_live_Zz9Yy8Xx_SECRET_SHOWN_ONCE")).toHaveCount(0);
    expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage) + location.href)).not.toContain("SECRET_SHOWN_ONCE");
    await expect(page.getByRole("table", { name: "API keys" })).toContainText("github-actions");
    expect(st.created).toEqual([{ name: "github-actions", scopes: ["read", "runs:write"] }]);
    await axeClean(page);
  });

  test("admin checks and locks the other scopes; revoke names the key", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/settings/api-keys");
    await page.getByRole("button", { name: "Create key" }).first().click();
    await page.getByRole("checkbox", { name: /^admin / }).check();
    await expect(page.getByRole("checkbox", { name: /^read / })).toBeDisabled();
    await page.getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "Actions for demo" }).click();
    await page.getByRole("menuitem", { name: "Revoke" }).click();
    await expect(page.getByText(/Revoke "demo"\? Anything using it stops working immediately\./)).toBeVisible();
  });
});

test.describe("audits", () => {
  const rows = [
    { id: CALL_ID, source: "upload", status: "completed", agent_id: null, language: "kn-IN", duration_ms: 30000, started_at: ts, overall_score: 52, passed: false, critical_failure: false, needs_human_review: true, review_reasons: ["judge_low_confidence"], failure_types: ["wrong_fact", "latency"], human_reviewed: false },
    { id: uuid(1001), source: "import", status: "transcribing", agent_id: null, language: "hi-IN", duration_ms: null, started_at: ts, overall_score: null, passed: null, critical_failure: null, needs_human_review: null, review_reasons: [], failure_types: [], human_reviewed: false },
  ];
  test("list shows score, verdict, flag, in-progress status and links to the call", async ({ page }) => {
    const st = opsState();
    st.extra["GET /calls"] = page_(rows);
    await mockFe(page, st);
    await page.goto("/audits");
    await expect(page.getByRole("heading", { level: 1, name: "Audits" })).toBeVisible();
    const table = page.getByRole("table", { name: "Audits" });
    await expect(table).toContainText("Fail");
    await expect(table).toContainText("transcribing");
    await expect(table).toContainText("webhook");
    await expect(table.getByRole("link").first()).toHaveAttribute("href", new RegExp(`/calls/${CALL_ID}`));
    await axeClean(page);
  });
  test("empty state offers upload and the webhook link", async ({ page }) => {
    const st = opsState();
    st.extra["GET /calls"] = page_([]);
    await mockFe(page, st);
    await page.goto("/audits");
    await expect(page.getByText("No audits yet")).toBeVisible();
    await expect(page.getByRole("link", { name: "Send calls automatically with a webhook" })).toBeVisible();
  });
  test("upload needs a file, an agent and consent; 501 is explained", async ({ page }) => {
    const st = opsState();
    st.extra["POST /audits"] = [501, { error: { code: "not_implemented", message: "x", details: {} } }];
    await mockFe(page, st);
    await page.route(/\/api\/proxy\/api\/v1\/audits$/, (r) => r.fulfill({ status: 501, json: { error: { code: "not_implemented", message: "x", details: {} } } }));
    await page.goto("/audits/new");
    const submit = page.getByRole("button", { name: "Upload and audit" });
    await expect(submit).toBeDisabled();
    await page.getByLabel("Audio file").setInputFiles({ name: "call.wav", mimeType: "audio/wav", buffer: Buffer.alloc(2000) });
    await page.getByLabel("Agent").selectOption({ index: 1 });
    await page.getByLabel(/I have the right to process/).check();
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.getByText(/Audits cannot be created in this build yet/)).toBeVisible();
    await axeClean(page);
  });
});

test.describe("integrations", () => {
  const connectors = [{ name: "webhook", direction: "both", subscribes_to: ["evaluation.completed"], config_schema: { properties: { url: { type: "string", title: "URL" } }, required: ["url"] }, secrets_schema: { properties: { token: { type: "string", title: "Token" } } } }];
  const integ = { id: uuid(1100), connector: "webhook", name: "Exotel webhook", direction: "both", enabled: true, config: { url: "https://example.com/h" }, secrets_set: true, event_filter: { events: ["evaluation.completed"], only_failed: false }, last_test_at: ts, last_test_ok: true, created_at: ts, updated_at: ts, inbound_url: "https://x/api/v1/webhooks/inbound/abc" };
  test("list, add with a generated form, one-time signing secret reveal", async ({ page }) => {
    const st = opsState();
    st.extra["GET /integrations/connectors"] = connectors;
    st.extra["GET /integrations"] = page_([integ]);
    st.extra["POST /integrations"] = [201, { ...integ, id: uuid(1101), name: "New hook", signing_secret: "whsec_ONLY_ONCE" }];
    await mockFe(page, st);
    await page.goto("/integrations");
    await expect(page.getByRole("table", { name: "Integrations" })).toContainText("Exotel webhook");
    await expect(page.getByText("Planned").first()).toBeVisible();
    await axeClean(page);
    await page.getByRole("button", { name: "Add integration" }).first().click();
    await page.getByLabel("Connector", { exact: true }).selectOption("webhook");
    await page.getByLabel("Name", { exact: true }).fill("New hook");
    await page.getByLabel("URL").fill("https://example.com/new");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByLabel("Signing secret", { exact: true })).toHaveValue("whsec_ONLY_ONCE");
    const close = page.getByRole("button", { name: "Close", exact: true }).last();
    await expect(close).toBeDisabled();
    await page.getByLabel("I copied it").check();
    await close.click();
    await expect(page.getByText("whsec_ONLY_ONCE")).toHaveCount(0);
  });
  test("detail: secrets show Set with Replace, deliveries can be redelivered", async ({ page }) => {
    const st = opsState();
    st.extra["GET /integrations/connectors"] = connectors;
    st.extra[`GET /integrations/${integ.id}`] = integ;
    st.extra[`GET /integrations/${integ.id}/deliveries`] = page_([{ id: uuid(1200), event_id: uuid(1201), direction: "outbound", status: "failed", http_status: 429, external_id: null, attempts: 3, response_excerpt: "rate limited", created_at: ts }]);
    st.extra[`POST /integrations/${integ.id}/deliveries/${uuid(1200)}/redeliver`] = [202, {}];
    await mockFe(page, st);
    await page.goto(`/integrations/${integ.id}`);
    await expect(page.getByText("Set", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Replace" })).toBeVisible();
    await page.getByRole("radio", { name: "Deliveries" }).click();
    await expect(page.getByRole("table", { name: "Deliveries" })).toContainText("429");
    await page.getByRole("button", { name: "Redeliver" }).click();
    await expect(page.getByText("Idempotent. If it already succeeded, nothing is sent twice.")).toBeVisible();
  });
  test("501 on the delivery log says so", async ({ page }) => {
    const st = opsState();
    st.extra["GET /integrations/connectors"] = connectors;
    st.extra[`GET /integrations/${integ.id}`] = integ;
    st.fail[`GET /integrations/${integ.id}/deliveries`] = 501;
    await mockFe(page, st);
    await page.goto(`/integrations/${integ.id}`);
    await page.getByRole("radio", { name: "Deliveries" }).click();
    await expect(page.getByText("The delivery log is not enabled in this build")).toBeVisible();
  });
});

test.describe("dialect", () => {
  const report = { id: uuid(1300), dataset_id: uuid(1301), progress: { done: 9, expected_results: 9 }, aggregates: { "North Karnataka": { clean_16k: { "gnani-prisma": { n: 24, wer: 0.18, wer_ci: [0.12, 0.25], cer: 0.08, entity_acc: 0.9 } }, pstn_street_10db: { "gnani-prisma": { n: 24, wer: 0.52, wer_ci: [0.41, 0.63], cer: 0.3, entity_acc: 0.71 } } }, "Coastal": { clean_16k: { "gnani-prisma": { n: 6, wer: 0.3, wer_ci: [0.1, 0.5], cer: 0.1, entity_acc: 0.8 } } } }, top_errors: [{ ref: "ನಾಲ್ಕು", hyp: "ನಾಕು", count: 5 }], bias_suggestions: ["EMI", "UPI"], created_at: ts };
  test("heatmap ranks the worst cell, hatches low n, switches metric, selects a cell", async ({ page }) => {
    const st = opsState();
    st.extra[`GET /dialect-reports/${report.id}`] = report;
    st.extra[`GET /dialect-reports/${report.id}/clips`] = page_([{ sample_id: "s1", dialect_label: "North Karnataka", condition: "pstn_street_10db", engine: "gnani-prisma", reference_text: "ನಾಲ್ಕು ಸಾವಿರ", hypothesis_text: "ನಾಕು ಸಾವಿರ", wer: 0.5, cer: 0.2, entity_total: 1, entity_correct: 0 }]);
    await mockFe(page, st);
    await page.goto(`/dialect/${report.id}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("North Karnataka on pstn_street_10db has the worst WER: 52%");
    await expect(page.getByRole("gridcell", { name: /Coastal, clean_16k.*low sample/ })).toBeVisible();
    await page.getByRole("radio", { name: "Entity accuracy" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("worst Entity accuracy: 71%");
    await page.getByRole("gridcell", { name: /North Karnataka, pstn_street_10db/ }).click();
    await expect(page.getByText("Worst clips")).toBeVisible();
    await expect(page.getByText("ನಾಕು ಸಾವಿರ")).toBeVisible();
    await expect(page.locator('[lang="kn"]').first()).toBeVisible();
    await axeClean(page);
  });
  test("not enabled when the API answers 501", async ({ page }) => {
    const st = opsState();
    st.fail["GET /dialect-"] = 501;
    await mockFe(page, st);
    await page.goto("/dialect");
    await expect(page.getByText("Dialect evaluation is not enabled in this build")).toBeVisible();
  });
});

test.describe("regression and calibration", () => {
  test("regression table with the tolerance arithmetic in the verdict tooltip", async ({ page }) => {
    const st = opsState();
    st.extra["GET /regression-tests"] = page_([{ id: uuid(1400), agent_id: uuid(101), scenario_id: uuid(1), scenario_title: "Wrong amount read-back", failure_type: "asr_misrecognition", status: "blocking", baseline_score: 80, tolerance: 5, notes: "", created_at: ts, last_score: 52, last_passed: false, source_call_id: CALL_ID }]);
    await mockFe(page, st);
    await page.goto("/regression");
    await expect(page.getByRole("table", { name: "Regression tests" })).toContainText("Wrong amount read-back");
    await expect(page.locator('[title="52 against 80 - 5 = 75"]')).toBeVisible();
    await expect(page.getByRole("button", { name: "Run regression suite" })).toBeEnabled();
    await axeClean(page);
  });
  test("regression 501 is a not-enabled state", async ({ page }) => {
    const st = opsState();
    st.fail["GET /regression-tests"] = 501;
    await mockFe(page, st);
    await page.goto("/regression");
    await expect(page.getByText("Regression tests is not enabled in this build")).toBeVisible();
  });
  test("calibration tiles and a below-target kappa sentence", async ({ page }) => {
    const st = opsState();
    st.extra["GET /calibration"] = { n: 32, kappa_pass_fail: 0.41, spearman_overall: 0.78, dimension_mae: { task_completion: 0.4, escalation: 0.1 } };
    await mockFe(page, st);
    await page.goto("/calibration");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("kappa 0.41 over 32 calls");
    await expect(page.getByText("Below the 0.6 target. The rubric should be revised and re-calibrated.")).toBeVisible();
    await expect(page.getByText("Task completion").first()).toBeVisible();
    await axeClean(page);
  });
  test("calibration 501", async ({ page }) => {
    const st = opsState();
    st.fail["GET /calibration"] = 501;
    await mockFe(page, st);
    await page.goto("/calibration");
    await expect(page.getByText("Calibration is not enabled in this build")).toBeVisible();
  });
});

// Visual self-review of pages whose endpoints are still 501 in the API: SYNTHETIC data through the mocked API, saved to proof/FE-05/screenshots-synthetic.
test.describe("synthetic-data screenshots", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`dialect, regression, calibration, integrations (${scheme})`, async ({ page }) => {
      test.slow();
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 1440, height: 900 });
      const st = opsState();
      const rid = uuid(1300);
      st.extra[`GET /dialect-reports/${rid}`] = { id: rid, dataset_id: uuid(1301), progress: { done: 12, expected_results: 12 }, aggregates: { "North Karnataka": { clean_16k: { "gnani-prisma": { n: 24, wer: 0.18, wer_ci: [0.12, 0.25], cer: 0.08, entity_acc: 0.9 } }, pstn_8k_alaw: { "gnani-prisma": { n: 24, wer: 0.33, wer_ci: [0.25, 0.41], cer: 0.14, entity_acc: 0.8 } }, pstn_street_10db: { "gnani-prisma": { n: 24, wer: 0.52, wer_ci: [0.41, 0.63], cer: 0.3, entity_acc: 0.71 } } }, "Coastal": { clean_16k: { "gnani-prisma": { n: 6, wer: 0.3, wer_ci: [0.1, 0.5], cer: 0.1, entity_acc: 0.8 } }, pstn_8k_alaw: { "gnani-prisma": { n: 31, wer: 0.12, wer_ci: [0.08, 0.17], cer: 0.05, entity_acc: 0.93 } }, pstn_street_10db: { "gnani-prisma": { n: 31, wer: 0.27, wer_ci: [0.2, 0.34], cer: 0.12, entity_acc: 0.84 } } } }, top_errors: [{ ref: "ನಾಲ್ಕು", hyp: "ನಾಕು", count: 5 }, { ref: "ಐನೂರು", hyp: "ಐನೂರ", count: 3 }], bias_suggestions: ["EMI", "UPI", "ಕಂತು"], created_at: ts };
      st.extra[`GET /dialect-reports/${rid}/clips`] = page_([]);
      st.extra["GET /regression-tests"] = page_([{ id: uuid(1400), agent_id: uuid(101), scenario_id: uuid(1), scenario_title: "Wrong amount read-back", failure_type: "asr_misrecognition", status: "blocking", baseline_score: 80, tolerance: 5, notes: "", created_at: ts, last_score: 52, last_passed: false, source_call_id: CALL_ID }, { id: uuid(1401), agent_id: uuid(101), scenario_id: uuid(2), scenario_title: "Disclosure within two turns", failure_type: "missing_disclosure", status: "blocking", baseline_score: 80, tolerance: 5, notes: "", created_at: ts, last_score: 91, last_passed: true, source_call_id: null }]);
      st.extra["GET /calibration"] = { n: 32, kappa_pass_fail: 0.71, spearman_overall: 0.78, dimension_mae: { task_completion: 0.4, factual_accuracy: 0.3, language_handling: 0.2, escalation: 0.1 } };
      st.extra["GET /integrations/connectors"] = [{ name: "hubspot", direction: "sink", subscribes_to: ["evaluation.completed"], config_schema: { properties: {} }, secrets_schema: { properties: {} } }, { name: "webhook", direction: "both", subscribes_to: ["evaluation.completed"], config_schema: { properties: {} }, secrets_schema: { properties: {} } }];
      st.extra["GET /integrations"] = page_([{ id: uuid(1100), connector: "hubspot", name: "HubSpot, collections", direction: "sink", enabled: true, config: {}, secrets_set: true, event_filter: { events: ["evaluation.completed"], only_failed: true }, last_test_at: ts, last_test_ok: true, created_at: ts, updated_at: ts }]);
      await mockFe(page, st);
      for (const [path, name] of [[`/dialect/${rid}`, "dialect-report"], ["/regression", "regression"], ["/calibration", "calibration"], ["/integrations", "integrations"]] as const) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await page.screenshot({ path: `../proof/FE-05/screenshots-synthetic/${name}-${scheme}.png`, fullPage: true });
      }
    });
  }
});
