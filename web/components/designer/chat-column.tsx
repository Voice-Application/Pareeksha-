"use client";

import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Check, CircleAlert } from "lucide-react";
import { ApiError } from "@/lib/api/call";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { controlClass, FieldError } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/states";
import { MAX_MESSAGE_CHARS, type Entry, type Question } from "./types";

/** Enter sends, Shift+Enter adds a line. An IME composing an Indic word keeps Enter for itself. */
function sendOnEnter(e: KeyboardEvent<HTMLTextAreaElement>, send: () => void) {
  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
    e.preventDefault();
    send();
  }
}

const count = (n: number) => n.toLocaleString("en-IN");

export function ChatColumn({
  log,
  pending,
  error,
  locked,
  text,
  onText,
  onSend,
  limitFor,
  onRetry,
  onEdit,
  onResend,
}: {
  log: Entry[];
  pending: boolean;
  error: unknown;
  /** The draft was created; the conversation is finished. */
  locked: boolean;
  text: string;
  onText: (v: string) => void;
  onSend: (text: string) => void;
  /** Why this text cannot be sent as the next message (conversation totals), or null. */
  limitFor: (text: string) => string | null;
  onRetry: () => void;
  onEdit: () => void;
  onResend: () => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  const last = log[log.length - 1];
  const awaitingReply = last?.role === "user";
  const tooLong = text.length > MAX_MESSAGE_CHARS;
  const limit = limitFor(text);
  const canSend =
    !!text.trim() && !tooLong && !limit && !awaitingReply && !locked;

  // Keep the newest line in view as the log grows (no smooth scroll: it is a state change, not decoration).
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [log.length, pending, error]);

  // After a reply lands, put focus on the first question or the composer so a keyboard user can carry on.
  const was = useRef(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (was.current && !pending && !error) {
      const first = root.current?.querySelector<HTMLElement>(
        "form button, form input",
      );
      (last?.questions?.length && first
        ? first
        : document.getElementById("designer-reply")
      )?.focus();
    }
    was.current = pending;
  }, [pending, error, last]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (canSend) onSend(text);
  }

  if (log.length === 0) {
    return (
      <Panel title="Conversation">
        <form onSubmit={submit} className="flex flex-col gap-2">
          <p className="max-w-[62ch] text-sm text-muted">
            Paste your voice bot&apos;s system prompt or workflow. The assistant
            reads it, asks only what it cannot work out, then drafts the agent
            and its tests beside this column.
          </p>
          <label htmlFor="designer-paste" className="mt-2 text-sm font-medium">
            Paste your bot&apos;s system prompt or workflow
          </label>
          <textarea
            id="designer-paste"
            value={text}
            onChange={(e) => onText(e.target.value)}
            onKeyDown={(e) => sendOnEnter(e, () => submit())}
            aria-invalid={tooLong || undefined}
            aria-describedby="designer-paste-help"
            spellCheck={false}
            className={cn(
              controlClass,
              "h-auto min-h-[320px] resize-y py-2 leading-6",
            )}
          />
          {limit ? (
            <FieldError id="designer-paste-help">{limit}</FieldError>
          ) : tooLong ? (
            <FieldError id="designer-paste-help">
              {count(text.length)} characters. One message can hold{" "}
              {count(MAX_MESSAGE_CHARS)}; trim the prompt to the parts that
              describe the call.
            </FieldError>
          ) : (
            <p id="designer-paste-help" className="text-xs text-subtle">
              <span className="num">{count(text.length)}</span> of{" "}
              <span className="num">{count(MAX_MESSAGE_CHARS)}</span>{" "}
              characters. Enter sends, Shift+Enter adds a line.
            </p>
          )}
          <div className="mt-2">
            <Button type="submit" variant="primary" disabled={!canSend}>
              Send
            </Button>
          </div>
        </form>
      </Panel>
    );
  }

  return (
    <Panel title="Conversation" bodyClassName="p-0">
      <div ref={root}>
        <ol aria-label="Conversation log" className="border-t border-border">
          {log.map((e, i) => (
            <Row key={i} role={e.role}>
              <Content text={e.content} long={e.role === "user"} />
              {e.questions &&
                e.questions.length > 0 &&
                (i === log.length - 1 && !locked ? (
                  <Questions key={i} questions={e.questions} onSend={onSend} />
                ) : (
                  <QuestionList questions={e.questions} />
                ))}
            </Row>
          ))}
          {pending && (
            <Row role="assistant">
              <div
                role="status"
                aria-label="Assistant is thinking"
                className="flex flex-col gap-2 pt-1"
              >
                <Skeleton className="w-3/4" />
              </div>
            </Row>
          )}
          {!pending && !!error && (
            <li className="border-b border-border px-5 py-4 last:border-0">
              <ChatError error={error} onRetry={onRetry} onEdit={onEdit} />
            </li>
          )}
          {!pending && !error && awaitingReply && (
            <li className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4 text-sm last:border-0">
              <span className="text-muted">
                This message has no reply yet. The page was probably reloaded
                while the assistant was answering.
              </span>
              <Button onClick={onResend}>Send again</Button>
            </li>
          )}
        </ol>
        <div ref={end} />
        {locked ? (
          <p className="border-t border-border px-5 py-4 text-sm text-muted">
            The draft is created. Start over to design another set of tests.
          </p>
        ) : (
          <form
            onSubmit={submit}
            className="flex flex-col gap-2 border-t border-border px-5 py-4"
          >
            <label htmlFor="designer-reply" className="text-sm font-medium">
              Reply
            </label>
            <textarea
              id="designer-reply"
              rows={3}
              value={text}
              onChange={(e) => onText(e.target.value)}
              onKeyDown={(e) => sendOnEnter(e, () => submit())}
              aria-invalid={tooLong || undefined}
              aria-describedby="designer-reply-help"
              className={cn(
                controlClass,
                "h-auto min-h-[76px] resize-y py-2 leading-6",
              )}
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              {limit ? (
                <FieldError id="designer-reply-help">
                  {limit} Start over to continue.
                </FieldError>
              ) : tooLong ? (
                <FieldError id="designer-reply-help">
                  {count(text.length)} characters. One message can hold{" "}
                  {count(MAX_MESSAGE_CHARS)}.
                </FieldError>
              ) : (
                <p id="designer-reply-help" className="text-xs text-subtle">
                  {awaitingReply
                    ? "Wait for the reply, or edit the last message."
                    : "Ask for changes to the draft. Enter sends, Shift+Enter adds a line."}
                </p>
              )}
              <Button type="submit" disabled={!canSend}>
                Send
              </Button>
            </div>
          </form>
        )}
      </div>
    </Panel>
  );
}

/** A labelled, left-aligned log line, as in the call transcript. */
function Row({
  role,
  children,
}: {
  role: Entry["role"];
  children: React.ReactNode;
}) {
  return (
    <li className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 border-b border-border px-5 py-4 last:border-0 max-[560px]:grid-cols-1 max-[560px]:gap-y-1">
      <span
        className={cn(
          "text-sm font-medium",
          role === "user" ? "text-muted" : "text-fg",
        )}
      >
        {role === "user" ? "You" : "Assistant"}
        <span className="sr-only">:</span>
      </span>
      <div className="min-w-0">{children}</div>
    </li>
  );
}

const CLIP = 600;

/** A pasted prompt can be thousands of characters; it is clipped until asked for. */
function Content({ text, long }: { text: string; long: boolean }) {
  const [open, setOpen] = useState(false);
  const clip = long && text.length > CLIP + 200;
  return (
    <div>
      <p
        className={cn(
          "text-base break-words whitespace-pre-wrap",
          long && "text-fg",
        )}
      >
        {clip && !open ? `${text.slice(0, CLIP).trimEnd()}…` : text}
      </p>
      {clip && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1 text-sm text-accent-fg underline underline-offset-2 hover:no-underline active:translate-y-px"
          aria-expanded={open}
        >
          {open ? "Show less" : `Show all ${count(text.length)} characters`}
        </button>
      )}
    </div>
  );
}

function QuestionList({ questions }: { questions: Question[] }) {
  return (
    <ol className="mt-3 flex list-decimal flex-col gap-1 pl-5 text-base marker:text-muted">
      {questions.map((q) => (
        <li key={q.id}>{q.text}</li>
      ))}
    </ol>
  );
}

type Answer = { picks: string[]; text: string };

/** The assistant's open questions: numbered, each with its options as chips plus a short free answer. One send for all of them. */
function Questions({
  questions,
  onSend,
}: {
  questions: Question[];
  onSend: (text: string) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const value = (q: Question) => {
    const a = answers[q.id];
    return [...(a?.picks ?? []), a?.text.trim() ?? ""]
      .filter(Boolean)
      .join(", ");
  };
  const answered = questions.filter((q) => value(q)).length;
  const update = (id: string, f: (a: Answer) => Answer) =>
    setAnswers((cur) => ({
      ...cur,
      [id]: f(cur[id] ?? { picks: [], text: "" }),
    }));
  const toggle = (id: string, option: string) =>
    update(id, (a) => ({
      ...a,
      picks: a.picks.includes(option)
        ? a.picks.filter((x) => x !== option)
        : [...a.picks, option],
    }));

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!answered) return;
    onSend(
      questions
        .map((q, i) => `${i + 1}. ${q.text}\n${value(q) || "No answer."}`)
        .join("\n\n"),
    );
  }

  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-4">
      <ol className="flex flex-col gap-4">
        {questions.map((q, i) => (
          <li
            key={q.id}
            className="grid grid-cols-[24px_minmax(0,1fr)] gap-x-1"
          >
            <span className="num text-base text-muted" aria-hidden>
              {i + 1}.
            </span>
            <fieldset className="min-w-0">
              <legend className="text-base">{q.text}</legend>
              {(q.options ?? []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(q.options ?? []).map((o) => {
                    const on = answers[q.id]?.picks.includes(o) ?? false;
                    return (
                      <button
                        key={o}
                        type="button"
                        aria-pressed={on}
                        onClick={() => toggle(q.id, o)}
                        className={cn(
                          "inline-flex h-8 items-center gap-1.5 rounded-pill border px-3 text-sm transition-[background-color,border-color,color,transform] duration-150 ease-out active:translate-y-px motion-reduce:transition-none motion-reduce:active:translate-y-0",
                          on
                            ? "border-accent bg-selected font-medium text-fg"
                            : "border-border-strong bg-surface text-fg hover:bg-hover",
                        )}
                      >
                        {on && (
                          <Check
                            size={12}
                            strokeWidth={2}
                            aria-hidden
                            className="text-accent-fg"
                          />
                        )}
                        {o}
                      </button>
                    );
                  })}
                </div>
              )}
              <input
                aria-label={`Answer ${i + 1} in your own words`}
                placeholder={
                  (q.options ?? []).length
                    ? "Or type a short answer"
                    : "Type a short answer"
                }
                value={answers[q.id]?.text ?? ""}
                onChange={(e) =>
                  update(q.id, (a) => ({ ...a, text: e.target.value }))
                }
                className={cn(controlClass, "mt-2 max-w-[420px]")}
              />
            </fieldset>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={!answered}>
          Send answers
        </Button>
        <span className="text-xs text-subtle">
          <span className="num">{answered}</span> of{" "}
          <span className="num">{questions.length}</span> answered. Unanswered
          ones are sent as &ldquo;No answer.&rdquo;
        </span>
      </div>
    </form>
  );
}

function causeOf(e: ApiError | null): string {
  if (!e) return "The API did not respond.";
  if (e.code === "designer_invalid_output")
    return "The assistant's reply could not be read. Retrying usually works.";
  if (e.code === "llm_not_configured")
    return "No LLM key is configured for this project.";
  if (e.code === "upstream_error")
    return `The LLM provider failed. ${e.message}`;
  return e.userMessage();
}

/** Inline error row in the assistant slot. Retry resends the same request; Edit puts the message back in the composer. */
function ChatError({
  error,
  onRetry,
  onEdit,
}: {
  error: unknown;
  onRetry: () => void;
  onEdit: () => void;
}) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-sm bg-fail-tint px-4 py-3 text-sm"
    >
      <CircleAlert
        size={16}
        strokeWidth={1.6}
        className="shrink-0 text-fail-fg"
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p>
          <span className="font-medium text-fail-fg">
            The assistant did not answer.{" "}
          </span>
          <span>{causeOf(e)}</span>
          {e?.requestId && (
            <span className="mono ml-2 text-xs text-muted">{e.requestId}</span>
          )}
        </p>
        {e?.code === "llm_not_configured" && (
          <p className="mt-1">
            <Link
              href="/settings/llm"
              className="text-accent-fg underline underline-offset-2 hover:no-underline"
            >
              Set up the LLM provider
            </Link>
          </p>
        )}
      </div>
      <div className="flex gap-2">
        <Button variant="ghost" onClick={onEdit}>
          Edit message
        </Button>
        {e?.status !== 422 && <Button onClick={onRetry}>Retry</Button>}
      </div>
    </div>
  );
}
