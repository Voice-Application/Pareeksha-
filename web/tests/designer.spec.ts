import { test, expect, type Page } from "@playwright/test";
import { freshState, mockApi, uuid } from "./support/mock-api";

const draft = (endpoint: string | null) => ({
  agent: {
    name: "Designer Bot",
    description: "",
    languages: ["hi-IN"],
    endpoint_url: endpoint,
    adapter: "audio_v1",
    glass_box: false,
    mandatory_disclosures: [{ id: "recording", text: "recorded" }],
    expected_tools: [{ name: "transfer_to_human" }],
  },
  scenarios: [
    {
      title: "Disputes the fee",
      caller_goal: "g",
      success_criteria: "s",
      reveal_rules: "",
      caller_speaks_first: false,
      max_turns: 10,
      tags: ["edge_case"],
    },
    {
      title: "Asks for callback",
      caller_goal: "g",
      success_criteria: "s",
      reveal_rules: "",
      caller_speaks_first: false,
      max_turns: 10,
      tags: [],
    },
  ],
  personas: [
    { existing_id: uuid(301) },
    { new: { name: "Brand new caller", language: "hi-IN" } },
  ],
  noise_profile_ids: [uuid(401), uuid(402)],
});

type Body = {
  messages: { role: string; content: string }[];
  draft: { agent: { endpoint_url: string } };
};
type Seen = { chat: { body: Body }[]; commit: { body: Body }[] };

async function open(
  page: Page,
  opts: {
    chat502?: boolean;
    oneScenario?: boolean;
    delay?: number;
    commitFail?: { status: number; message: string; details?: object };
  } = {},
) {
  const state = freshState();
  await mockApi(page, state);
  const seen: Seen = { chat: [], commit: [] };
  let turn = 0;
  // Registered after mockApi, so it answers first for /designer/*.
  await page.route(/\/api\/proxy\/api\/v1\/designer\//, async (route) => {
    const req = route.request();
    const body = req.postDataJSON();
    if (req.url().endsWith("/designer/commit")) {
      if (opts.commitFail)
        return route.fulfill({
          status: opts.commitFail.status,
          json: {
            error: {
              code: "validation_error",
              message: opts.commitFail.message,
              details: opts.commitFail.details ?? {},
            },
          },
        });
      seen.commit.push({ body });
      return route.fulfill({
        status: 201,
        json: {
          agent_id: uuid(555),
          scenario_ids: [uuid(1), uuid(2)],
          persona_ids: [uuid(3)],
          noise_profile_ids: [uuid(4)],
          calls: 8,
          run_wizard_path: "/runs/new?agent_id=" + uuid(555),
        },
      });
    }
    seen.chat.push({ body });
    if (opts.chat502 && seen.chat.length === 1) {
      return route.fulfill({
        status: 502,
        json: {
          error: {
            code: "designer_invalid_output",
            message: "bad",
            details: {},
          },
        },
        headers: { "x-request-id": "req_test_0001" },
      });
    }
    turn++;
    if (opts.delay) await new Promise((r) => setTimeout(r, opts.delay));
    if (turn === 1 && !opts.oneScenario)
      return route.fulfill({
        json: {
          reply: "Two questions.",
          questions: [
            {
              id: "q1",
              text: "Which language?",
              options: ["Hindi", "Kannada"],
            },
            { id: "q2", text: "Is it recorded?", options: [] },
          ],
          draft: null,
          ready: false,
        },
      });
    return route.fulfill({
      json: {
        reply: "Drafted.",
        questions: [],
        draft: opts.oneScenario
          ? { ...draft(null), scenarios: draft(null).scenarios.slice(0, 1) }
          : draft(null),
        ready: true,
      },
    });
  });
  await page.goto("/designer");
  return seen;
}

test.describe("Designer", () => {
  test("prompt, questions, draft, endpoint, create all, start run", async ({
    page,
  }) => {
    const seen = await open(page);
    await expect(page.getByText("Nothing drafted yet")).toBeVisible();
    await page
      .getByLabel("Paste your bot's system prompt or workflow")
      .fill("You are an EMI reminder bot.");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByText("Which language?").first()).toBeVisible();
    await page.getByRole("button", { name: "Hindi" }).click();
    await page.getByLabel("Answer 2 in your own words").fill("Yes");
    await page.getByRole("button", { name: "Send answers" }).click();

    // The answers went out as one user message, with the whole history.
    await expect(page.getByText("Drafted.", { exact: true })).toBeVisible();
    expect(seen.chat[1].body.messages).toHaveLength(3);
    expect(seen.chat[1].body.messages[2].content).toContain("Hindi");

    // Draft fills; create is blocked until the endpoint is set.
    await expect(page.getByText("Disputes the fee")).toBeVisible();
    await expect(page.getByText("Brand new caller")).toBeVisible();
    await expect(page.getByText("2 × 2 × 2 = 8 calls")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create all" }),
    ).toBeDisabled();
    await page.getByLabel("Endpoint URL").fill("ws://bot:8765/ws");
    await page.getByRole("button", { name: "Create all" }).click();

    await expect(page.getByRole("link", { name: "Start run" })).toHaveAttribute(
      "href",
      "/runs/new?agent_id=" + uuid(555),
    );
    expect(seen.commit[0].body.draft.agent.endpoint_url).toBe(
      "ws://bot:8765/ws",
    );
  });

  test("a 502 shows an inline error and Retry resends the same request", async ({
    page,
  }) => {
    const seen = await open(page, { chat502: true });
    await page
      .getByLabel("Paste your bot's system prompt or workflow")
      .fill("prompt");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "The assistant did not answer" });
    await expect(alert).toBeVisible();
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByText("Which language?").first()).toBeVisible();
    expect(seen.chat).toHaveLength(2);
    expect(seen.chat[1].body).toEqual(seen.chat[0].body);
  });

  test("the last scenario cannot be removed", async ({ page }) => {
    await open(page, { oneScenario: true });
    await page
      .getByLabel("Paste your bot's system prompt or workflow")
      .fill("prompt");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText("Disputes the fee")).toBeVisible();
    const remove = page.getByRole("button", {
      name: "Remove scenario Disputes the fee",
    });
    await expect(remove).toBeDisabled();
    await expect(remove).toHaveAttribute("title", /at least one scenario/);
  });

  test("a conversation over the total character limit is blocked before any request", async ({
    page,
  }) => {
    const seen = await open(page);
    const box = page.getByLabel("Paste your bot's system prompt or workflow");
    await box.fill("a".repeat(19_000));
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText("Which language?").first()).toBeVisible();
    // Three more long messages would pass 60,000 characters in total.
    const reply = page.getByLabel("Reply", { exact: true });
    for (let i = 0; i < 2; i++) {
      await reply.fill("b".repeat(19_000));
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByText("Drafted.", { exact: true })).toHaveCount(i + 1);
    }
    await reply.fill("c".repeat(19_000));
    await expect(page.getByText(/character limit/).first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Send", exact: true }),
    ).toBeDisabled();
    expect(seen.chat).toHaveLength(3); // the first message and two replies; the fourth never goes out
  });

  test("Start over is disabled while a request is pending and a late reply does not come back", async ({
    page,
  }) => {
    await open(page, { delay: 600 });
    await page
      .getByLabel("Paste your bot's system prompt or workflow")
      .fill("prompt");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Start over" }),
    ).toBeDisabled();
    await expect(page.getByText("Which language?").first()).toBeVisible();
    await page.getByRole("button", { name: "Start over" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Start over" })
      .click();
    await expect(page.getByText("Nothing drafted yet")).toBeVisible();
    await expect(page.getByText("Which language?")).toHaveCount(0);
  });

  test("a commit 422 about something else is not shown under the endpoint field", async ({
    page,
  }) => {
    await open(page, {
      commitFail: { status: 422, message: "Scenario count out of range." },
    });
    await page
      .getByLabel("Paste your bot's system prompt or workflow")
      .fill("prompt");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByRole("button", { name: "Hindi" }).click();
    await page.getByRole("button", { name: "Send answers" }).click();
    await page.getByLabel("Endpoint URL").fill("ws://bot:8765/ws");
    await page.getByRole("button", { name: "Create all" }).click();
    const msg = page.getByText("Scenario count out of range.");
    await expect(msg).toBeVisible();
    await expect(page.getByLabel("Endpoint URL")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  test("a commit 422 naming the endpoint is shown at the endpoint field", async ({
    page,
  }) => {
    await open(page, {
      commitFail: {
        status: 422,
        message: "Invalid draft.",
        details: { field: "draft.agent.endpoint_url" },
      },
    });
    await page
      .getByLabel("Paste your bot's system prompt or workflow")
      .fill("prompt");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByRole("button", { name: "Hindi" }).click();
    await page.getByRole("button", { name: "Send answers" }).click();
    await page.getByLabel("Endpoint URL").fill("ws://bot:8765/ws");
    await page.getByRole("button", { name: "Create all" }).click();
    await expect(page.getByLabel("Endpoint URL")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });
});
