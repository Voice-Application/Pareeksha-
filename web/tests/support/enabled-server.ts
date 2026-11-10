import { spawn, type ChildProcess } from "node:child_process";
import { access } from "node:fs/promises";

/**
 * Starts the shared build (made with sign-in enabled) as a second `next start` with the account gate on.
 * The main test server on :3100 runs with AUTH_DISABLED=1, where every visitor is an admin; specs that need
 * the role to matter run against one of these instead. Each spec file uses its own port.
 */
export function signInEnabledServer(port: number, secret: string, env: Record<string, string> = {}) {
  const url = `http://127.0.0.1:${port}`;
  let server: ChildProcess | undefined;

  async function start() {
    // PW_REUSE can bypass Playwright's build command. Ensure next start has a production build.
    try {
      await access(".next/BUILD_ID");
    } catch {
      await new Promise<void>((resolve, reject) => {
        const build = spawn(process.execPath, ["node_modules/next/dist/bin/next", "build"], {
          env: { ...process.env, AUTH_DISABLED: "0" }, stdio: ["ignore", "pipe", "pipe"],
        });
        let output = "";
        const capture = (chunk: Buffer) => { output = (output + chunk.toString()).slice(-16_000); };
        build.stdout.on("data", capture);
        build.stderr.on("data", capture);
        build.once("error", reject);
        build.once("exit", (code, signal) => code === 0 ? resolve() : reject(new Error(`Production build failed (${code ?? signal}):\n${output}`)));
      });
    }
    let output = "";
    let startupError: Error | undefined;
    server = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", String(port), "-H", "127.0.0.1"], {
      env: { ...process.env, ...env, AUTH_DISABLED: "0", SESSION_SECRET: secret },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const child = server;
    const capture = (chunk: Buffer) => { output = (output + chunk.toString()).slice(-16_000); };
    child.stdout!.on("data", capture);
    child.stderr!.on("data", capture);
    child.once("error", (error) => { startupError = error; });
    const assertRunning = () => {
      if (startupError || child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`Sign-in server failed (${startupError?.message ?? child.exitCode ?? child.signalCode}):\n${output}`);
      }
    };
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      assertRunning();
      try {
        const response = await fetch(`${url}/login`, { signal: AbortSignal.timeout(1000) });
        assertRunning();
        if (response.status === 200) return;
      } catch {
        assertRunning();
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`Sign-in server readiness timed out:\n${output}`);
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
