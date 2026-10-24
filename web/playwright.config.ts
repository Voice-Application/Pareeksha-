import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.spec\.ts/,
  reporter: [["list"], ["json", { outputFile: "test-results/report.json" }]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH || undefined },
  },
  webServer: {
    command: "npm run build && npx next start -p 3100 -H 127.0.0.1",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: false,
    timeout: 240_000,
    env: {
      PAREEKSHA_API_URL: "http://127.0.0.1:3199/api/v1",
      PAREEKSHA_API_KEY: "pk_test_fe01_secret",
      WEB_PASSWORD: "",
    },
  },
});
