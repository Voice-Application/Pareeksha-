import { test, expect, type Page } from "@playwright/test";
import { freshState, mockApi, uuid, type MockState } from "./support/mock-api";

async function open(page: Page, path: string, mutate?: (s: MockState) => void) {
  const state = freshState();
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(path);
  return state;
}

test.describe("Noise profiles list", () => {
  test("loading skeleton, then profiles ordered from clean to hostile", async ({ page }) => {
    await open(page, "/noise-profiles", (s) => (s.delay = 700));
    await expect(page.getByRole("heading", { level: 1, name: "Noise profiles", exact: true })).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading noise profiles" })).toBeVisible();
    await expect(page.getByRole("link", { name: "clean_16k" })).toBeVisible();
    const names = await page.getByRole("row").evaluateAll((rows) => rows.slice(1).map((r) => r.querySelector("a")?.textContent));
    expect(names).toEqual(["clean_16k", "mobile_weak_signal", "pstn_market_5db", "auto_rickshaw_0db"]);
    await expect(page.getByText("4 profiles", { exact: true })).toBeVisible();
  });

  test("rows show rate, codec, background, SNR with a bar, and icon chips only when loss or clipping is on", async ({ page }) => {
    await open(page, "/noise-profiles");
    const weak = page.getByRole("row", { name: /mobile_weak_signal/ });
    await expect(weak).toContainText("8 kHz");
    await expect(weak).toContainText("A-law");
    await expect(weak).toContainText("street_traffic");
    await expect(weak).toContainText("10 dB");
    await expect(weak).toContainText("5%");
    await expect(weak.getByTitle("Packet loss is on")).toBeVisible();
    await expect(weak.getByTitle("Clipping is on")).toBeVisible();
    const market = page.getByRole("row", { name: /pstn_market_5db/ });
    await expect(market.getByTitle("Packet loss is on")).toHaveCount(0);
    await expect(market.getByTitle("Clipping is on")).toHaveCount(0);
    await expect(page.getByRole("row", { name: /clean_16k/ })).toContainText("none");
  });

  test("empty state and error state", async ({ page }) => {
    await open(page, "/noise-profiles", (s) => (s.noise = []));
    await expect(page.getByRole("heading", { name: "No noise profiles" })).toBeVisible();
    await expect(page.getByText("make demo")).toBeVisible();
  });

  test("error state with Retry", async ({ page }) => {
    const s = await open(page, "/noise-profiles", (st) => (st.fail = [{ match: "GET /noise-profiles", status: 500, message: "Query failed." }]));
    const alert = page.getByRole("alert").filter({ hasText: "Could not load noise profiles" });
    await expect(alert).toBeVisible();
    s.fail = [];
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByRole("link", { name: "clean_16k" })).toBeVisible();
  });

  test("row preview plays the default sample for that profile", async ({ page }) => {
    const s = await open(page, "/noise-profiles");
    await page.getByRole("button", { name: "Play preview of pstn_market_5db" }).click();
    await expect(page.getByRole("button", { name: "Pause preview of pstn_market_5db" })).toBeVisible();
    expect(s.calls.some((c) => c.method === "POST" && c.path === `/noise-profiles/${uuid(402)}/preview`)).toBe(true);
  });
});

test.describe("Noise profile editor", () => {
  test("opens in a Sheet and edits with PATCH", async ({ page }) => {
    const s = await open(page, "/noise-profiles");
    await page.getByRole("link", { name: "pstn_market_5db" }).click();
    const dlg = page.getByRole("dialog", { name: "pstn_market_5db" });
    await expect(dlg.getByLabel("Name")).toHaveValue("pstn_market_5db");
    await expect(dlg.getByRole("radio", { name: "8 kHz" })).toBeChecked();
    await expect(dlg.getByRole("radio", { name: "A-law" })).toBeChecked();
    await expect(dlg.getByText("India's landline network uses A-law.")).toBeVisible();
    await dlg.getByLabel("SNR").fill("7");
    await expect(dlg.locator("output").first()).toHaveText("7 dB");
    await dlg.getByLabel("Packet loss").fill("2.5");
    await dlg.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved pstn_market_5db." })).toBeVisible();
    expect(s.calls.find((c) => c.method === "PATCH")?.body).toMatchObject({ snr_db: 7, packet_loss_pct: 2.5, background_category: "market_crowd" });
  });

  test("SNR is disabled without a background; 16 kHz with a bandpass is warned", async ({ page }) => {
    await open(page, "/noise-profiles?edit=" + uuid(401));
    const dlg = page.getByRole("dialog", { name: "clean_16k" });
    await expect(dlg.getByLabel("SNR")).toBeDisabled();
    await expect(dlg.getByText("Choose a background to set the signal-to-noise ratio.")).toBeVisible();
    await expect(dlg.getByText("Phone lines are 8 kHz.")).toHaveCount(0);
    await dlg.getByRole("switch", { name: "PSTN bandpass" }).click();
    await expect(dlg.getByText("Phone lines are 8 kHz. This profile will sound unrealistic.")).toBeVisible();
    await dlg.getByLabel("Background").selectOption("street_traffic");
    await expect(dlg.getByLabel("SNR")).toBeEnabled();
  });

  test("new profile: slug validation and unique name", async ({ page }) => {
    const s = await open(page, "/noise-profiles");
    await page.getByRole("button", { name: "New profile" }).click();
    const dlg = page.getByRole("dialog", { name: "New noise profile" });
    await dlg.getByLabel("Name").fill("Not A Slug");
    await dlg.getByRole("button", { name: "Create profile" }).click();
    await expect(dlg.getByText(/Use lowercase letters, digits and underscores/).first()).toBeVisible();
    await expect(dlg.getByLabel("Name")).toBeFocused();
    await dlg.getByLabel("Name").fill("clean_16k");
    await dlg.getByRole("button", { name: "Create profile" }).click();
    await expect(dlg.getByRole("alert").filter({ hasText: "A noise profile with this name already exists." })).toBeVisible();
    await dlg.getByLabel("Name").fill("pstn_train_8db");
    await dlg.getByLabel("Background").selectOption("bus_interior");
    await dlg.getByRole("button", { name: "Create profile" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Created pstn_train_8db." })).toBeVisible();
    expect(s.calls.filter((c) => c.method === "POST" && c.path === "/noise-profiles").pop()?.body).toMatchObject({ name: "pstn_train_8db", sample_rate: 8000, codec: "alaw", background_category: "bus_interior", snr_db: 15 });
  });

  test("My clip rejects a wrong file type and accepts a WAV for original vs processed playback", async ({ page }) => {
    const s = await open(page, "/noise-profiles?edit=" + uuid(402));
    const dlg = page.getByRole("dialog", { name: "pstn_market_5db" });
    await dlg.getByRole("radio", { name: "My clip" }).click();
    await expect(dlg.getByRole("button", { name: "Play processed clip" })).toBeDisabled();
    await dlg.getByLabel("Audio file").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
    await expect(dlg.getByRole("alert").filter({ hasText: "Use a WAV or MP3 under 10 MB." })).toBeVisible();
    await dlg.getByLabel("Audio file").setInputFiles({ name: "call.wav", mimeType: "audio/wav", buffer: Buffer.alloc(2000) });
    await expect(dlg.getByText("call.wav")).toBeVisible();
    await expect(dlg.getByRole("button", { name: "Original" })).toBeVisible();
    await dlg.getByRole("button", { name: "Processed" }).click();
    await expect(dlg.getByRole("button", { name: "Pause" }).or(dlg.getByRole("button", { name: "Processed" }))).toBeVisible();
    await expect.poll(() => s.calls.some((c) => c.method === "POST" && c.path.endsWith("/preview"))).toBe(true);
    await dlg.getByRole("button", { name: "Remove file" }).click();
    await expect(dlg.getByText("call.wav")).toHaveCount(0);
  });

  test("a 409 on delete lists the runs", async ({ page }) => {
    await open(page, "/noise-profiles?edit=" + uuid(402), (s) => (s.fail = [{ match: "DELETE /noise-profiles/", status: 409, code: "conflict", message: "This profile is used by 1 run.", details: { runs: [{ id: uuid(700), name: "Nightly matrix" }] } }]));
    const dlg = page.getByRole("dialog", { name: "pstn_market_5db" });
    await dlg.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("dialog", { name: "Delete pstn_market_5db?" }).getByRole("button", { name: "Delete profile" }).click();
    await expect(page.getByRole("dialog", { name: "pstn_market_5db is in use" })).toContainText("used by 1 run");
  });

  test("delete succeeds when unused", async ({ page }) => {
    const s = await open(page, "/noise-profiles?edit=" + uuid(403));
    await page.getByRole("dialog", { name: "auto_rickshaw_0db" }).getByRole("button", { name: "Delete" }).click();
    await page.getByRole("dialog", { name: "Delete auto_rickshaw_0db?" }).getByRole("button", { name: "Delete profile" }).click();
    await expect(page.getByRole("link", { name: "auto_rickshaw_0db" })).toHaveCount(0);
    expect(s.noise).toHaveLength(3);
  });

  test("deep link page and unknown id", async ({ page }) => {
    await open(page, "/noise-profiles/" + uuid(404));
    await expect(page.getByRole("heading", { level: 1, name: "mobile_weak_signal" })).toBeVisible();
    await page.goto("/noise-profiles/" + uuid(999));
    await expect(page.getByRole("heading", { name: "This item does not exist or was deleted" })).toBeVisible();
  });
});
