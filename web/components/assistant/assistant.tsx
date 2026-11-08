"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, MessageCircle, RotateCcw, Send, X } from "lucide-react";
import { ApiError } from "@/lib/api/call";
import { askAssistant, createQuickTest, getQuickTest, inr, quickTestPoll, UUID_RE, verdictLine, type AssistantResponse } from "@/lib/api/quick-tests";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { controlClass } from "@/components/ui/field";
import { ProgressBar } from "@/components/ui/measure";

type Entry = { role: "user" | "assistant"; content: string; res?: AssistantResponse; failed?: boolean };

const STORE = "pareeksha.assistant";
const MAX_CHARS = 60_000;
const STARTERS = ["What can Pareeksha do?", "Test my prompt", "How does a RAG test work?"];
const HELLO =
  "Hi, I can explain any part of Pareeksha, or test your bot for you. Paste your bot's system prompt here (and some made-up customer data if it uses any), and I will start the test.";

function load(): Entry[] {
  try {
    const raw = window.sessionStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Entry[]) : [];
  } catch {
    return [];
  }
}

/** Enter sends, Shift+Enter adds a line; an IME composing a word keeps Enter for itself. */
function onEnter(e: KeyboardEvent<HTMLTextAreaElement>, send: () => void) {
  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
    e.preventDefault();
    send();
  }
}

/** The assistant on every page: a button at the bottom right that opens a chat beside the page. */
export function Assistant() {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  // Closed on the server and on first paint, so reading sessionStorage here cannot mismatch.
  const [log, setLog] = useState<Entry[]>(() => (typeof window === "undefined" ? [] : load()));
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORE, JSON.stringify(log.slice(-40)));
    } catch {
      /* storage full or blocked: the chat still works */
    }
  }, [log]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [log, open]);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  const page = pathname.split("?")[0];
  const seg = page.split("/");
  const current = seg[1] === "test" && UUID_RE.test(seg[2] ?? "") ? seg[2] : null;

  const ask = useMutation({
    mutationFn: (history: Entry[]) =>
      askAssistant({
        messages: history.filter((e) => !e.failed).slice(-30).map((e) => ({ role: e.role, content: e.content })),
        page,
        quick_test_id: current,
      }),
    onSuccess: (res) => {
      setLog((l) => [...l, { role: "assistant", content: res.reply, res }]);
      if (res.quick_test_id) void qc.invalidateQueries({ queryKey: ["quick-tests"] });
      if (res.open_path) router.push(res.open_path);
    },
    onError: (e) => {
      const why = e instanceof ApiError ? e.userMessage() : "The API did not respond.";
      setLog((l) => [...l, { role: "assistant", content: `Sorry, that did not work: ${why}`, failed: true }]);
    },
  });

  function send(value: string) {
    const v = value.trim();
    if (!v || ask.isPending || v.length > MAX_CHARS) return;
    const next: Entry[] = [...log, { role: "user", content: v }];
    setLog(next);
    setText("");
    ask.mutate(next);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    send(text);
  }

  const last = log[log.length - 1];
  const suggestions = !log.length ? STARTERS : last?.role === "assistant" ? (last.res?.suggestions ?? []) : [];

  if (!open)
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed right-4 bottom-4 z-30 inline-flex h-11 items-center gap-2 rounded-pill border border-accent bg-accent px-4 text-sm font-medium text-accent-on transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hi active:translate-y-px min-[561px]:right-6 min-[561px]:bottom-6"
        style={{ boxShadow: "var(--shadow-float)" }}
      >
        <MessageCircle size={16} strokeWidth={1.6} aria-hidden />
        Ask Pareeksha
      </button>
    );

  return (
    <section
      aria-label="Pareeksha assistant"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
      className="fixed inset-x-2 bottom-2 z-30 flex max-h-[calc(100dvh-16px)] flex-col overflow-hidden rounded-lg border border-border bg-surface min-[561px]:inset-x-auto min-[561px]:right-6 min-[561px]:bottom-6 min-[561px]:h-[min(680px,calc(100dvh-96px))] min-[561px]:w-[420px]"
      style={{ boxShadow: "var(--shadow-float)", height: "min(680px, calc(100dvh - 16px))" }}
    >
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border pr-2 pl-4">
        <h2 className="text-md font-medium">Ask Pareeksha</h2>
        <div className="ml-auto flex items-center">
          {log.length > 0 && (
            <Button variant="ghost" icon aria-label="Start a new conversation" title="New conversation" onClick={() => setLog([])} disabled={ask.isPending}>
              <RotateCcw size={16} strokeWidth={1.6} aria-hidden />
            </Button>
          )}
          <Button variant="ghost" icon aria-label="Close the assistant" onClick={() => setOpen(false)}>
            <X size={16} strokeWidth={1.6} aria-hidden />
          </Button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
        <div className="flex flex-col gap-4">
          <Bubble role="assistant" content={HELLO} />
          {log.map((e, i) => (
            <div key={i} className="flex flex-col gap-2">
              <Bubble role={e.role} content={e.content} failed={e.failed} />
              {e.res && <Outcome res={e.res} onStarted={(id) => setLog((l) => [...l, { role: "assistant", content: "Started. The results update below and on the test page.", res: { reply: "", suggestions: [], quick_test_id: id } }])} />}
            </div>
          ))}
          {ask.isPending && (
            <p className="flex items-center gap-2 text-sm text-muted" role="status">
              <span className="spinner" aria-hidden />
              {/prompt|test/i.test(last?.content ?? "") ? "Working on it. Starting a test takes up to a minute." : "Thinking…"}
            </p>
          )}
          <div ref={end} />
        </div>
      </div>
      {suggestions.length > 0 && !ask.isPending && (
        <div className="flex flex-wrap gap-2 px-4 pb-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => (s === "Test my prompt" && !log.length ? (setText("Test this prompt:\n"), input.current?.focus()) : send(s))}
              className="rounded-pill border border-border-strong px-3 py-1 text-sm text-fg transition-colors hover:bg-hover"
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="flex shrink-0 items-end gap-2 border-t border-border p-3">
        <label htmlFor="assistant-input" className="sr-only">
          Message to the assistant
        </label>
        <textarea
          id="assistant-input"
          ref={input}
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => onEnter(e, () => send(text))}
          placeholder="Ask anything, or paste your bot's prompt"
          className={cn(controlClass, "h-auto max-h-48 min-h-[44px] resize-none py-2 leading-5")}
          aria-invalid={text.length > MAX_CHARS || undefined}
        />
        <Button type="submit" variant="primary" icon aria-label="Send" disabled={!text.trim() || ask.isPending || text.length > MAX_CHARS}>
          <Send size={16} strokeWidth={1.6} aria-hidden />
        </Button>
      </form>
    </section>
  );
}

function Bubble({ role, content, failed }: { role: Entry["role"]; content: string; failed?: boolean }) {
  if (!content) return null;
  const mine = role === "user";
  return (
    <div className={cn("max-w-[92%] rounded-md px-3 py-2 text-sm whitespace-pre-wrap", mine ? "self-end bg-accent-tint text-fg" : "self-start bg-sunken", failed && "bg-fail-tint")}>
      {mine && content.length > 600 ? `${content.slice(0, 600)}… (${content.length.toLocaleString("en-IN")} characters)` : content}
    </div>
  );
}

/** What an assistant turn did: a live test card, a rewrite summary, or a cost to accept. */
function Outcome({ res, onStarted }: { res: AssistantResponse; onStarted: (id: string) => void }) {
  const start = useMutation({ mutationFn: () => createQuickTest({ ...res.pending!, confirm_cost: true }), onSuccess: (t) => onStarted(t.id) });
  return (
    <>
      {res.improvement && (
        <div className="rounded-md border border-border px-3 py-2 text-sm">
          <p className="font-medium">
            New prompt: {res.improvement.prompt_chars_before.toLocaleString("en-IN")} → {res.improvement.prompt_chars_after.toLocaleString("en-IN")} characters
          </p>
          {(res.improvement.changes ?? []).slice(0, 4).map((c) => (
            <p key={c} className="mt-1 text-muted">
              · {c}
            </p>
          ))}
          {(res.improvement.doc_suggestions ?? []).length > 0 && <p className="mt-1 text-muted">{(res.improvement.doc_suggestions ?? []).length} document fix(es) suggested on the test page.</p>}
        </div>
      )}
      {res.quick_test_id && <TestCard id={res.quick_test_id} />}
      {res.pending && res.estimate && !start.isSuccess && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" loading={start.isPending} onClick={() => start.mutate()}>
            Run for {inr(res.estimate.est_cost)}
          </Button>
          {start.isError && <span className="text-sm text-fail-fg">{start.error instanceof ApiError ? start.error.userMessage() : "It did not start."}</span>}
        </div>
      )}
    </>
  );
}

function TestCard({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["quick-test", id], queryFn: () => getQuickTest(id), refetchInterval: (s) => quickTestPoll(s.state.data?.status) });
  if (!q.data)
    return (
      <div className="rounded-md border border-border px-3 py-2 text-sm text-muted" role="status">
        Loading the test…
      </div>
    );
  const t = q.data;
  const live = t.status === "running" || t.status === "checking";
  const broken = t.rules.filter((r) => r.status === "broken");
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border px-3 py-3 text-sm">
      <p className="font-medium">{verdictLine(t)}</p>
      {live && <ProgressBar done={t.status === "running" ? t.progress.finished : t.progress.checked} total={t.progress.total} label="Test progress" />}
      {broken.slice(0, 3).map((r) => (
        <p key={r.id} className="text-fail-fg">
          Broken: {r.text}
          {r.evidence?.[0]?.quote ? <span className="block text-muted">“{r.evidence[0].quote}”</span> : null}
        </p>
      ))}
      <Link href={`/test/${t.id}`} className="inline-flex items-center gap-1 self-start text-accent-fg underline-offset-2 hover:underline">
        Open the results <ArrowRight size={14} strokeWidth={1.6} aria-hidden />
      </Link>
    </div>
  );
}
