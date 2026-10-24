"use client";

import { useEffect, useRef, useState } from "react";
import { CircleCheck, CircleX, Plug } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { CONNECTION_FIX } from "@/lib/format";
import { Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";

type Result = components["schemas"]["TestConnectionResult"];
type State = { phase: "idle" } | { phase: "running"; elapsed: number } | { phase: "done"; result: Result } | { phase: "error"; message: string };

/** Right-hand panel on the agent editor (agents spec, ConnectionTest). Needs a saved agent. */
export function ConnectionTest({ agentId, settingsKey, autoRun }: { agentId: string | null; settingsKey: string; autoRun?: boolean }) {
  const [state, setState] = useState<State>({ phase: "idle" });
  const [ranWith, setRanWith] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  function stop() {
    abort.current?.abort();
    if (timer.current) clearInterval(timer.current);
  }
  useEffect(() => stop, []);

  async function run() {
    if (!agentId) return;
    stop();
    setRanWith(settingsKey);
    const ctl = new AbortController();
    abort.current = ctl;
    const started = Date.now();
    setState({ phase: "running", elapsed: 0 });
    timer.current = setInterval(() => setState({ phase: "running", elapsed: Math.floor((Date.now() - started) / 1000) }), 500);
    try {
      const result = await call(api.POST("/api/v1/agents/{agent_id}/test-connection", { params: { path: { agent_id: agentId } }, signal: ctl.signal }));
      setState({ phase: "done", result });
    } catch (e) {
      if (ctl.signal.aborted) setState({ phase: "idle" });
      else setState({ phase: "error", message: e instanceof ApiError ? e.userMessage() : "The request failed." });
    } finally {
      if (timer.current) clearInterval(timer.current);
    }
  }

  const ran = useRef(false);
  useEffect(() => {
    if (autoRun && agentId && !ran.current) {
      ran.current = true;
      void run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, agentId]);

  const running = state.phase === "running";
  return (
    <Panel title="Connection test" bodyClassName="flex flex-col gap-3">
      <p className="text-sm text-muted">Opens the socket, sends 1 s of silence and waits up to 10 s for the agent to speak.</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" disabled={!agentId || running} loading={false} onClick={() => void run()} aria-describedby="conn-hint">
          <Plug size={14} strokeWidth={1.6} aria-hidden />
          Test connection
        </Button>
        {running && (
          <Button variant="ghost" onClick={stop}>
            Cancel
          </Button>
        )}
      </div>
      {!agentId && (
        <p id="conn-hint" className="text-xs text-subtle">
          Save the agent first.
        </p>
      )}

      <div role="status" aria-live="polite" className="flex flex-col gap-2">
        {running && (
          <>
            <div className="h-1 overflow-hidden rounded-xs bg-sunken" aria-hidden>
              <div className="skeleton h-1 w-1/3" style={{ background: "var(--accent)" }} />
            </div>
            <p className="text-sm">
              Waiting for agent audio, <span className="mono">{state.elapsed}</span> s of up to <span className="mono">10</span> s.
            </p>
          </>
        )}
        {state.phase === "done" && state.result.ok && (
          <div className="flex gap-2 border-l-2 border-pass bg-pass-tint px-3 py-2 text-sm">
            <CircleCheck size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-pass-fg" aria-hidden />
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <dt className="text-muted">Status</dt>
              <dd className="mono">ok</dd>
              <dt className="text-muted">First audio</dt>
              <dd className="mono">{state.result.first_audio_ms} ms</dd>
              <dt className="text-muted">Protocol</dt>
              <dd className="mono">{state.result.protocol ?? "-"}</dd>
              <dt className="text-muted">Glass-box messages</dt>
              <dd>{state.result.glass_box_messages_seen == null ? "-" : state.result.glass_box_messages_seen ? "seen" : "not seen"}</dd>
            </dl>
          </div>
        )}
        {state.phase === "done" && !state.result.ok && (
          <div role="alert" className="flex gap-2 border-l-2 border-fail bg-fail-tint px-3 py-2 text-sm">
            <CircleX size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-fail-fg" aria-hidden />
            <div>
              <p>
                <span className="mono font-medium">{state.result.error ?? "failed"}</span>
                {state.result.detail && <span className="ml-2">{state.result.detail}</span>}
              </p>
              {state.result.error && CONNECTION_FIX[state.result.error] && <p className="mt-1 text-muted">{CONNECTION_FIX[state.result.error]}</p>}
            </div>
          </div>
        )}
        {state.phase === "error" && (
          <div role="alert" className="flex gap-2 border-l-2 border-fail bg-fail-tint px-3 py-2 text-sm">
            <CircleX size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-fail-fg" aria-hidden />
            <p>Could not run the test. {state.message}</p>
          </div>
        )}
        {ranWith !== null && ranWith !== settingsKey && state.phase === "done" && <p className="text-xs text-subtle">Result is for the previous settings.</p>}
      </div>
    </Panel>
  );
}
