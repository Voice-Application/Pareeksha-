import { defineConfig } from "@playwright/test";

/**
 * QA-04: specs that run against the REAL stack (no mocks). Start the stack (`docker compose --profile workers up -d`,
 * seeded, with at least one finished run), then serve the web app against it:
 *
 *   PAREEKSHA_API_URL=http://127.0.0.1:8000/api/v1 PAREEKSHA_API_KEY=... npm run build && npx next start -p 3200
 *   REAL_WEB_URL=http://127.0.0.1:3200 REAL_API_URL=http://127.0.0.1:8000/api/v1 PAREEKSHA_API_KEY=... npm run test:real
 *
 * The API key is only used by the test process to look up ids and to scan for leaks; it never goes to the browser.
 */
export default defineConfig({
  testDir: "./tests/real",
  testMatch: /.*\.spec\.ts/,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "test-results/real-report.json" }]],
  use: {
    baseURL: process.env.REAL_WEB_URL ?? "http://127.0.0.1:3200",
    launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH || undefined },
  },
});
