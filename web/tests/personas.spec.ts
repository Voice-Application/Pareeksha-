import { test, expect, type Page } from "@playwright/test";
import { freshState, mockApi, uuid, type MockState } from "./support/mock-api";

async function open(page: Page, path: string, mutate?: (s: MockState) => void) {
  const state = freshState();
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(path);
  return state;
}

test.describe("Personas list", () => {
  test("loading skeleton, then rows with pips, seed chip and language counts", async ({ page }) => {
    await open(page, "/personas", (s) => (s.delay = 700));
    await expect(page.getByRole("heading", { level: 1, name: "Personas", exact: true })).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading personas" })).toBeVisible();
    const row = page.getByRole("row", { name: /Manju, frustrated Kanglish/ });
    await expect(row).toBeVisible();
    await expect(row).toContainText("kn-IN");
    await expect(row).toContainText("heavy");
    await expect(row).toContainText("1.1x");
    await expect(row).toContainText("Prakash");
    await expect(row).toContainText("seed");
    await expect(row.getByText("often interrupts", { exact: false }).or(row.getByText("Often"))).toHaveCount(1);
    await expect(page.getByText("3 personas: 1 Kannada, 1 Hindi, 1 English")).toBeVisible();
    // User-made personas carry no seed chip.
    await expect(page.getByRole("row", { name: /Custom English/ })).not.toContainText("seed");
  });

  test("filters by language on the server and by emotion in the client", async ({ page }) => {
    const s = await open(page, "/personas");
    await page.getByLabel("Language", { exact: true }).selectOption("hi-IN");
    await expect.poll(() => s.calls.some((c) => c.path === "/personas" && c.query.get("language") === "hi-IN")).toBe(true);
    await expect(page.getByRole("link", { name: "Priya, polite Hindi" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Custom English" })).toHaveCount(0);
    await page.getByRole("button", { name: "Clear", exact: true }).click();
    await page.getByLabel("Emotion", { exact: true }).selectOption("neutral");
    await expect(page.getByRole("link", { name: "Custom English" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Priya, polite Hindi" })).toHaveCount(0);
  });

  test("sorting by speed toggles ascending and descending", async ({ page }) => {
    await open(page, "/personas");
    await page.getByRole("button", { name: "Speed" }).click();
    await expect(page).toHaveURL(/sort=speed%3Aasc/);
    const first = page.getByRole("row").nth(1);
    await expect(first).toContainText("Custom English");
    await page.getByRole("button", { name: "Speed" }).click();
    await expect(page.getByRole("row").nth(1)).toContainText("Manju");
  });

  test("empty and error states", async ({ page }) => {
    await open(page, "/personas", (s) => (s.personas = []));
    await expect(page.getByRole("heading", { name: "No personas yet" })).toBeVisible();
    await expect(page.getByText("make demo")).toBeVisible();
    await page.getByRole("main").getByRole("button", { name: "New persona" }).last().click();
    await expect(page.getByRole("dialog", { name: "New persona" })).toBeVisible();
  });

  test("error state with Retry", async ({ page }) => {
    const s = await open(page, "/personas", (st) => (st.fail = [{ match: "GET /personas", status: 500, message: "Query failed." }]));
    const alert = page.getByRole("alert").filter({ hasText: "Could not load personas" });
    await expect(alert).toBeVisible();
    s.fail = [];
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByRole("link", { name: "Custom English" })).toBeVisible();
  });

  test("the row play button fetches the preview and only one clip plays at a time", async ({ page }) => {
    const s = await open(page, "/personas");
    const a = page.getByRole("button", { name: "Play preview of Manju, frustrated Kanglish" });
    const b = page.getByRole("button", { name: "Play preview of Priya, polite Hindi" });
    await a.click();
    await expect(page.getByRole("button", { name: "Pause preview of Manju, frustrated Kanglish" })).toBeVisible();
    expect(s.calls.some((c) => c.method === "POST" && c.path === `/personas/${uuid(301)}/preview`)).toBe(true);
    await b.click();
    await expect(page.getByRole("button", { name: "Pause preview of Priya, polite Hindi" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause preview of Manju, frustrated Kanglish" })).toHaveCount(0);
  });

  test("a failed row preview reports the reason", async ({ page }) => {
    await open(page, "/personas", (s) => (s.fail = [{ match: "POST /personas/", status: 502, code: "upstream_error", message: "Gnani TTS is out of credits." }]));
    await page.getByRole("button", { name: "Play preview of Manju, frustrated Kanglish" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Could not synthesise: Gnani TTS is out of credits." })).toBeVisible();
  });
});

test.describe("Persona editor", () => {
  test("clicking a name opens the Sheet with the persona and keeps a deep link", async ({ page }) => {
    await open(page, "/personas");
    await page.getByRole("link", { name: "Manju, frustrated Kanglish" }).click();
    const dlg = page.getByRole("dialog", { name: "Manju, frustrated Kanglish" });
    await expect(dlg).toBeVisible();
    await expect(page).toHaveURL(/edit=00000000/);
    await expect(dlg.getByLabel("Name")).toHaveValue("Manju, frustrated Kanglish");
    await expect(dlg.getByLabel("Voice", { exact: true })).toHaveValue("Prakash");
    await expect(dlg.getByText("Do not use a real person's voice.")).toBeVisible();
    await expect(dlg.getByText("Descriptive only. We do not claim the voice is that dialect.")).toBeVisible();
    await expect(dlg.getByRole("radio", { name: "2" })).toBeChecked();
    // Esc closes and the focus goes back to where it came from.
    await page.keyboard.press("Escape");
    await expect(dlg).toBeHidden();
    await expect(page).not.toHaveURL(/edit=/);
  });

  test("edit saves with PATCH; preview is enabled only for saved settings", async ({ page }) => {
    const s = await open(page, "/personas?edit=" + uuid(301));
    const dlg = page.getByRole("dialog", { name: "Manju, frustrated Kanglish" });
    const play = dlg.getByRole("button", { name: "Play sample line" });
    await expect(play).toBeEnabled();
    await dlg.getByLabel("Emotion").selectOption("angry");
    await expect(play).toBeDisabled();
    await expect(dlg.getByText(/Save your changes to preview them/)).toBeVisible();
    await dlg.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved Manju" })).toBeVisible();
    expect(s.calls.find((c) => c.method === "PATCH" && c.path === `/personas/${uuid(301)}`)?.body).toMatchObject({ emotion: "angry", speed: 1.1, interruption_level: 2 });
    await expect(play).toBeEnabled();
    await play.click();
    await expect(dlg.getByRole("button", { name: "Pause" })).toBeVisible();
    await expect(dlg.getByText(/\d\.\d s/)).toBeVisible();
  });

  test("a preview failure is inline and leaves the form editable", async ({ page }) => {
    await open(page, "/personas?edit=" + uuid(301), (s) => (s.fail = [{ match: "POST /personas/", status: 502, code: "upstream_error", message: "Gnani returned 429." }]));
    const dlg = page.getByRole("dialog", { name: "Manju, frustrated Kanglish" });
    await dlg.getByRole("button", { name: "Play sample line" }).click();
    await expect(dlg.getByRole("alert")).toContainText("Could not synthesise: Gnani returned 429.");
    await expect(dlg.getByRole("alert").getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(dlg.getByLabel("Name")).toBeEditable();
  });

  test("new persona: validation, same-voice warning, create", async ({ page }) => {
    const s = await open(page, "/personas");
    await page.getByRole("button", { name: "New persona" }).click();
    const dlg = page.getByRole("dialog", { name: "New persona" });
    await expect(dlg.getByRole("button", { name: "Play sample line" })).toBeDisabled();
    await expect(dlg.getByText("Save the persona to preview its voice.")).toBeVisible();
    await dlg.getByRole("button", { name: "Create persona" }).click();
    await expect(dlg.getByRole("alert")).toContainText("Fix 1 field before saving.");
    await expect(dlg.getByLabel("Name")).toBeFocused();
    await dlg.getByLabel("Name").fill("Lakshmi, anxious Hindi");
    await dlg.getByLabel("Language").selectOption("hi-IN");
    await dlg.getByLabel("Voice", { exact: true }).selectOption("Shivani");
    await expect(dlg.getByText("Same voice as Priya, polite Hindi, hi-IN")).toBeVisible();
    await dlg.getByLabel("Emotion").selectOption("anxious");
    await dlg.getByRole("radio", { name: "3" }).click();
    await dlg.getByRole("button", { name: "Create persona" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Created Lakshmi, anxious Hindi." })).toBeVisible();
    expect(s.calls.find((c) => c.method === "POST" && c.path === "/personas")?.body).toMatchObject({ name: "Lakshmi, anxious Hindi", language: "hi-IN", voice_id: "Shivani", emotion: "anxious", interruption_level: 3, tts_model: "timbre-v3.0" });
  });

  test("closing a dirty Sheet asks before discarding", async ({ page }) => {
    await open(page, "/personas?edit=" + uuid(301));
    const dlg = page.getByRole("dialog", { name: "Manju, frustrated Kanglish" });
    await dlg.getByLabel("Name").fill("Changed");
    await dlg.getByRole("button", { name: "Close" }).click();
    const confirm = page.getByRole("dialog", { name: "Discard changes?" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(dlg.getByLabel("Name")).toHaveValue("Changed");
    await dlg.getByRole("button", { name: "Close" }).click();
    await page.getByRole("dialog", { name: "Discard changes?" }).getByRole("button", { name: "Discard changes" }).click();
    await expect(page).not.toHaveURL(/edit=/);
  });

  test("delete is confirmed by name; a 409 lists the runs", async ({ page }) => {
    await open(page, "/personas?edit=" + uuid(301), (s) => (s.fail = [{ match: "DELETE /personas/", status: 409, code: "conflict", message: "This persona is used by 2 runs.", details: { runs: [{ id: uuid(700), name: "Nightly matrix" }] } }]));
    const dlg = page.getByRole("dialog", { name: "Manju, frustrated Kanglish" });
    await dlg.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("dialog", { name: "Delete Manju, frustrated Kanglish?" }).getByRole("button", { name: "Delete persona" }).click();
    const refused = page.getByRole("dialog", { name: "Manju, frustrated Kanglish is in use" });
    await expect(refused).toContainText("used by 2 runs");
    await expect(refused.getByRole("link", { name: "Nightly matrix" })).toBeVisible();
  });

  test("the deep link page renders the same editor", async ({ page }) => {
    await open(page, "/personas/" + uuid(303));
    await expect(page.getByRole("heading", { level: 1, name: "Custom English" })).toBeVisible();
    await expect(page.getByLabel("Name")).toHaveValue("Custom English");
    await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  test("an unknown persona shows a page error", async ({ page }) => {
    await open(page, "/personas/" + uuid(999));
    await expect(page.getByRole("heading", { name: "This item does not exist or was deleted" })).toBeVisible();
  });
});
