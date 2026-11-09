import { expect } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";

/**
 * Starts the shared build (made with sign-in enabled) as a second `next start` with the account gate on.
 * The main test server on :3100 runs with AUTH_DISABLED=1, where every visitor is an admin; specs that need
 * the role to matter run against one of these instead. Each spec file uses its own port.
 */
export function signInEnabledServer(port: number, secret: string) {
  const url = `http://127.0.0.1:${port}`;
  let server: ChildProcess | undefined;

  async function start() {
    server = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", String(port), "-H", "127.0.0.1"], {
      env: { ...process.env, AUTH_DISABLED: "0", SESSION_SECRET: secret },
      stdio: "ignore",
    });
    await expect.poll(async () => {
      try { return (await fetch(`${url}/login`)).status; } catch { return 0; }
    }, { timeout: 30_000 }).toBe(200);
  }

  async function stop() {
    const child = server;
    if (child && child.exitCode === null) {
      await new Promise<void>((resolve) => {
        child.once("exit", () => resolve());
        child.kill();
      });
    }
  }

  return { url, start, stop };
}
