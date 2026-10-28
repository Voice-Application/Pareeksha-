import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.spec\.ts/,
  testIgnore: "**/real/**", // real-stack specs run via playwright.real.config.ts (QA-04)
  reporter: [["list"], ["json", { outputFile: "test-results/report.json" }]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH || undefined },
  },
  webServer: {
    command: "npm run build && npx next start -p 3100 -H 127.0.0.1",
    url: "http://127.0.0.1:3100",
    // PW_REUSE=1 lets a developer keep one `next start` running between local test runs; CI always builds fresh.
    reuseExistingServer: !!process.env.PW_REUSE,
    timeout: 240_000,
    env: {
      PAREEKSHA_API_URL: "http://127.0.0.1:3199/api/v1",
      PAREEKSHA_API_KEY: "pk_test_fe01_secret",
      WEB_PASSWORD: "",
    },
  },
});
