"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { ApiError, call } from "@/lib/api/call";
import { PageHeader } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/overlay";
import { ChatColumn } from "./chat-column";
import { DraftPanel } from "./draft-panel";
import {
  MAX_MESSAGES,
  MAX_TOTAL_CHARS,
  toTurns,
  type Committed,
  type Draft,
  type Entry,
  type Saved,
} from "./types";

const KEY = "pareeksha.designer.v1";

const isEntry = (e: unknown) => {
  const x = e as {
    role?: unknown;
    content?: unknown;
    questions?: unknown;
  } | null;
  return (
    !!x &&
    (x.role === "user" || x.role === "assistant") &&
    typeof x.content === "string" &&
    (x.questions === undefined || Array.isArray(x.questions))
  );
};

function load(): Saved | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Partial<Saved> | null;
    const d = s?.draft as
      | {
          agent?: unknown;
          scenarios?: unknown;
          personas?: unknown;
          noise_profile_ids?: unknown;
        }
      | null
      | undefined;
    const draftOk =
      d === null ||
      d === undefined ||
      (typeof d === "object" &&
        !!d.agent &&
        typeof d.agent === "object" &&
        Array.isArray(d.scenarios) &&
        Array.isArray(d.personas) &&
        Array.isArray(d.noise_profile_ids));
    const c = s?.committed as
      { agent_id?: unknown; run_wizard_path?: unknown } | null | undefined;
    const commitOk =
      c === null ||
      c === undefined ||
      (typeof c.agent_id === "string" && typeof c.run_wizard_path === "string");
    if (
      !s ||
      !Array.isArray(s.log) ||
      !s.log.every(isEntry) ||
      !draftOk ||
      !commitOk
    )
      return null;
    return {
      log: s.log,
      draft: s.draft ?? null,
      ready: s.ready === true,
      committed: s.committed ?? null,
    };
  } catch {
    return null;
  }
}

/** The API takes at most 40 messages and 60,000 characters in total (docs/06-api-spec.md section 14). */
function limitOf(entries: Entry[]): string | null {
  const turns = toTurns(entries);
  if (turns.length > MAX_MESSAGES)
    return `This conversation has reached the ${MAX_MESSAGES} message limit.`;
  if (turns.reduce((n, t) => n + t.content.length, 0) > MAX_TOTAL_CHARS)
    return `This conversation has reached the ${MAX_TOTAL_CHARS.toLocaleString("en-IN")} character limit.`;
  return null;
}

const noop = () => () => {};

/** Renders on the client only, so state can start from sessionStorage without a hydration mismatch. */
export function DesignerPage() {
  const mounted = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  return mounted ? <Designer saved={load()} /> : null;
}

function Designer({ saved }: { saved: Saved | null }) {
  const [log, setLog] = useState<Entry[]>(saved?.log ?? []);
  const [draft, setDraft] = useState<Draft | null>(saved?.draft ?? null);
  const [ready, setReady] = useState(saved?.ready ?? false);
  const [committed, setCommitted] = useState<Committed | null>(
    saved?.committed ?? null,
  );
  const [text, setText] = useState("");
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    try {
      sessionStorage.setItem(
        KEY,
        JSON.stringify({ log, draft, ready, committed } satisfies Saved),
      );
    } catch {
      /* storage blocked: the page still works, it just will not survive a reload */
    }
  }, [log, draft, ready, committed]);

  // Bumped by Start over: a reply to a request started before it must not repopulate the cleared page.
  const gen = useRef(0);
  const [notice, setNotice] = useState<string | null>(null);

  const chat = useMutation({
    mutationFn: (v: { l: Entry[]; draft: Draft | null; g: number }) =>
      call(
        api.POST("/api/v1/designer/chat", {
          body: { messages: toTurns(v.l), draft: v.draft } as never,
        }),
      ),
    onSuccess: (r, v) => {
      if (v.g !== gen.current) return;
      setLog((cur) => [
        ...cur,
        { role: "assistant", content: r.reply, questions: r.questions ?? [] },
      ]);
      if (r.draft) setDraft(r.draft);
      setReady(r.ready);
    },
  });

  const commit = useMutation({
    mutationFn: (v: { d: Draft; g: number }) =>
      call(
        api.POST("/api/v1/designer/commit", { body: { draft: v.d } as never }),
      ),
    onSuccess: (r, v) => {
      if (v.g === gen.current)
        setCommitted({
          ...r,
          agent_name: v.d.agent.name,
          new_personas: v.d.personas.filter((p) => "new" in p).length,
        });
    },
  });

  const limitFor = (t: string) =>
    limitOf([...log, { role: "user", content: t }]);

  function ask(l: Entry[]) {
    const m = limitOf(l);
    if (m) return setNotice(m);
    setNotice(null);
    chat.mutate({ l, draft, g: gen.current });
  }

  function send(content: string) {
    const next: Entry[] = [...log, { role: "user", content }];
    if (limitOf(next)) return;
    setLog(next);
    setText("");
    ask(next);
  }

  function edit() {
    const last = log[log.length - 1];
    if (last?.role !== "user") return;
    setText(last.content);
    setLog(log.slice(0, -1));
    chat.reset();
  }

  function reset() {
    gen.current++;
    setNotice(null);
    setLog([]);
    setDraft(null);
    setReady(false);
    setCommitted(null);
    setText("");
    chat.reset();
    commit.reset();
    setConfirm(false);
  }

  const ce = commit.error instanceof ApiError ? commit.error : null;
  const namesEndpoint = (c: ApiError) =>
    `${c.message} ${JSON.stringify(c.details)}`.includes("endpoint_url");
  const commitError = ce
    ? ce.status === 409
      ? {
          field: "name" as const,
          message:
            "An agent with this name already exists. Ask the assistant to rename it.",
        }
      : {
          field:
            ce.status === 422 && namesEndpoint(ce)
              ? ("endpoint" as const)
              : ("other" as const),
          message: ce.userMessage(),
        }
    : commit.isError
      ? { field: "other" as const, message: "Could not create." }
      : null;
  const last = log[log.length - 1];
  const busy = chat.isPending || commit.isPending;

  return (
    <>
      <PageHeader
        title="Test designer"
        description="Paste your bot's prompt once. The assistant drafts the agent, scenarios, callers and phone lines, and you create them in one step."
        actions={
          log.length > 0 && (
            <Button
              variant="ghost"
              disabled={busy}
              title={
                busy ? "Wait for the current request to finish." : undefined
              }
              onClick={() => setConfirm(true)}
            >
              Start over
            </Button>
          )
        }
      />
      <div aria-live="polite" className="sr-only">
        {!chat.isPending && last?.role === "assistant"
          ? `Assistant: ${last.content} ${(last.questions ?? []).map((q, i) => `Question ${i + 1}: ${q.text}`).join(" ")}`
          : ""}
      </div>
      {notice && (
        <div
          role="alert"
          className="mb-4 flex flex-wrap items-center gap-3 rounded-sm bg-fail-tint px-4 py-3 text-sm"
        >
          <span className="flex-1">
            {notice} Nothing was sent. Start over to design with a shorter
            conversation.
          </span>
          <Button disabled={busy} onClick={() => setConfirm(true)}>
            Start over
          </Button>
        </div>
      )}
      <div className="grid grid-cols-1 items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_440px]">
        <ChatColumn
          log={log}
          pending={chat.isPending}
          error={chat.error}
          locked={!!committed}
          text={text}
          onText={setText}
          onSend={send}
          limitFor={limitFor}
          onRetry={() => ask(log)}
          onEdit={edit}
          onResend={() => ask(log)}
        />
        <aside
          aria-label="Draft"
          className="min-w-0 min-[1180px]:sticky min-[1180px]:top-16"
        >
          <DraftPanel
            draft={draft}
            committed={committed}
            creating={commit.isPending}
            locked={chat.isPending}
            error={commitError}
            onEndpoint={(v) => {
              commit.reset();
              setDraft((d) =>
                d ? { ...d, agent: { ...d.agent, endpoint_url: v } } : d,
              );
            }}
            onRemoveScenario={(i) =>
              setDraft((d) =>
                d
                  ? { ...d, scenarios: d.scenarios.filter((_, j) => j !== i) }
                  : d,
              )
            }
            onCreate={() =>
              draft && commit.mutate({ d: draft, g: gen.current })
            }
          />
          {ready && !committed && (
            <p className="mt-2 text-xs text-subtle">
              The assistant considers this draft complete.
            </p>
          )}
        </aside>
      </div>
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Start over?"
        body="This clears the conversation and the draft. Anything already created stays."
        confirmLabel="Start over"
        onConfirm={reset}
      />
    </>
  );
}
