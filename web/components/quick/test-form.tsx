"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, FlaskConical, History, Play, SlidersHorizontal } from "lucide-react";
import { ApiError } from "@/lib/api/call";
import { asList, createQuickTest, getSetup, inr, listPoll, listQuickTests, type CostEstimate, type QuickTestCreate } from "@/lib/api/quick-tests";
import { relativeTime } from "@/lib/format";
import { PageHeader, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { Segmented, SelectField, TextAreaField, TextField } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { EmptyState, ErrorPanel, Strip, TableSkeleton } from "@/components/ui/states";
import { QuickStatus } from "./status";

import type { LucideIcon } from "lucide-react";

const linkCls = "text-accent-fg underline-offset-2 hover:underline";
const DETAILS_EXAMPLE = "Name: Ravi Kumar\nDate of birth: 12-03-1988\nLoan: SF-20931, EMI Rs 4,850 due 5 Nov\nPhone: 98450 00000";

/** A panel heading with its section glyph beside the words, so each block reads at a glance. */
function SectionTitle({ icon: Icon, children }: { icon: LucideIcon; children: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Icon size={16} strokeWidth={1.6} className="text-muted" aria-hidden />
      {children}
    </span>
  );
}

/** The one screen most people need: paste a prompt, optionally test data and documents, press the button. */
export function QuickTestForm() {
  const router = useRouter();
  const setup = useQuery({ queryKey: ["quick-setup"], queryFn: getSetup });
  const [prompt, setPrompt] = useState("");
  const [details, setDetails] = useState("");
  const [kb, setKb] = useState("");
  const [focus, setFocus] = useState("");
  const [count, setCount] = useState(8);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ body: QuickTestCreate; estimate: CostEstimate } | null>(null);

  const start = useMutation({
    mutationFn: createQuickTest,
    onSuccess: (t) => router.push(`/test/${t.id}`),
    onError: (e, body) => {
      if (e instanceof ApiError && e.code === "confirm_cost") {
        setConfirm({ body: { ...body, plan: e.details.plan as QuickTestCreate["plan"], confirm_cost: true }, estimate: e.details.estimate as CostEstimate });
        return;
      }
      setError(e instanceof ApiError ? e.userMessage() : "The API did not respond.");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (setup.isError) {
      setError("The documents list did not load. Try again first, so the test uses the documents you meant.");
      return;
    }
    if (!prompt.trim()) {
      setError("Paste your bot's system prompt first.");
      document.getElementById("qt-prompt")?.focus();
      return;
    }
    start.mutate({ system_prompt: prompt, user_details: details, kb_id: kb || null, instructions: focus, scenario_count: count, confirm_cost: false });
  }

  const kbs = setup.data?.knowledge_bases ?? [];
  const ready = setup.data?.llm_ready ?? true;

  return (
    <>
      <PageHeader
        title="Test my prompt"
        description="Paste your bot's system prompt. Pareeksha finds the rules in it, chats with your bot as normal and tricky customers, and shows which rules it keeps and the exact line where it breaks one."
      />
      {setup.isError && (
        <div className="mb-6" role="alert">
          <Strip tone="warn">
            {setup.error instanceof ApiError ? setup.error.userMessage() : "The setup details did not load."}{" "}
            <button type="button" className={linkCls} onClick={() => void setup.refetch()}>
              Try again
            </button>
          </Strip>
        </div>
      )}
      {!ready && (
        <div className="mb-6">
          <Strip tone="warn">
            Pareeksha needs an AI key to run your prompt and play the customers. An admin can add it under <Link className={linkCls} href="/settings/llm">Settings, LLM</Link>.
          </Strip>
        </div>
      )}
      <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_380px]">
        <form onSubmit={submit} noValidate aria-label="Test my prompt" className="flex min-w-0 flex-col gap-6">
          <Panel title={<SectionTitle icon={Bot}>Your bot</SectionTitle>} bodyClassName="flex flex-col gap-5">
            <TextAreaField
              id="qt-prompt"
              label="System prompt"
              required
              rows={12}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={"You are the helpdesk of Sahay Finance.\nOnly share loan details after the customer confirms their date of birth.\nNever promise to waive a fee. ..."}
              help={`${prompt.length.toLocaleString("en-IN")} characters, about ${Math.ceil(prompt.length / 4).toLocaleString("en-IN")} tokens.`}
              error={error && !prompt.trim() ? error : null}
            />
            <TextAreaField
              id="qt-details"
              label="Test customer data (optional)"
              rows={5}
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              placeholder={DETAILS_EXAMPLE}
              help="What the bot knows about the customer it talks to. Use made-up values. It is added to the prompt as the customer record, or put where you wrote {{user_details}}. Pareeksha then checks the bot does not give it away."
            />
          </Panel>
          <Panel title={<SectionTitle icon={SlidersHorizontal}>Options</SectionTitle>} bodyClassName="grid gap-5 min-[720px]:grid-cols-2">
            <SelectField
              id="qt-kb"
              label="Documents the bot answers from (optional)"
              value={kb}
              onChange={(e) => setKb(e.target.value)}
              help={
                <>
                  Turns this into a RAG test: answers are checked against the documents. <Link className={linkCls} href="/knowledge-bases">Add documents</Link>
                </>
              }
            >
              <option value="">No documents</option>
              {kbs.map((k) => (
                <option key={k.id} value={k.id} disabled={!k.ready}>
                  {k.name} ({k.documents} file{k.documents === 1 ? "" : "s"}){k.ready ? "" : ", still indexing"}
                </option>
              ))}
            </SelectField>
            <TextField id="qt-focus" label="Anything to focus on? (optional)" value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="e.g. people pretending to be the customer" />
            <Segmented
              label="Conversations"
              value={count}
              onChange={setCount}
              options={[
                { value: 4, label: "4, quick" },
                { value: 8, label: "8" },
                { value: 12, label: "12, thorough" },
              ]}
            />
          </Panel>
          {error && prompt.trim() && <Strip tone="error">{error}</Strip>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="primary" loading={start.isPending} disabled={!ready}>
              <Play size={14} strokeWidth={1.6} aria-hidden />
              {start.isPending ? "Reading your prompt" : "Test my prompt"}
            </Button>
            <p className="text-sm text-muted" aria-live="polite">
              {start.isPending ? "Finding the rules and writing the conversations. This takes up to a minute." : setup.data ? `Runs on ${setup.data.agent_model}. Starts at once when it costs ${inr(setup.data.auto_run_limit)} or less.` : ""}
            </p>
          </div>
        </form>
        <RecentTests />
      </div>
      <Dialog
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title="Run this test?"
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Not now</Button>
            <Button
              variant="primary"
              loading={start.isPending}
              onClick={() => {
                if (confirm) start.mutate(confirm.body);
                setConfirm(null);
              }}
            >
              Run for {inr(confirm?.estimate.est_cost)}
            </Button>
          </>
        }
      >
        <p className="text-sm">
          {confirm?.estimate.conversations} conversations are estimated at {inr(confirm?.estimate.est_cost)}, above the {inr(confirm?.estimate.limit)} that runs without asking. The estimate assumes every conversation runs to its longest, so the real cost is usually lower.
        </p>
      </Dialog>
    </>
  );
}

function RecentTests() {
  const q = useQuery({ queryKey: ["quick-tests"], queryFn: listQuickTests, refetchInterval: (s) => listPoll(s.state.data) });
  const list = asList(q.data);
  return (
    <Panel title={<SectionTitle icon={History}>Recent tests</SectionTitle>} bodyClassName="p-0 pb-2">
      {q.isPending && <TableSkeleton rows={3} label="Loading tests" />}
      {q.isError && (
        <div className="px-5 pb-4">
          <ErrorPanel error={q.error} what="tests" onRetry={() => void q.refetch()} />
        </div>
      )}
      {q.isSuccess && !list.length && <EmptyState icon={FlaskConical} title="No tests yet" body="Your tests show up here, newest first." />}
      {list.length > 0 && (
        <ul className="stagger flex flex-col divide-y divide-border">
          {list.slice(0, 8).map((t, i) => (
            <li key={t.id} style={{ ["--i" as string]: i }} className="group relative flex gap-3 px-5 py-3 transition-colors hover:bg-hover">
              <FlaskConical size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-subtle transition-colors group-hover:text-muted" aria-hidden />
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <Link href={`/test/${t.id}`} className="truncate font-medium after:absolute after:inset-0 group-hover:text-fg">
                  {t.name}
                  {t.parent_id ? " (improved)" : ""}
                </Link>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                  <QuickStatus status={t.status} broken={t.rules_broken} total={t.rules_total} untested={t.rules_untested} />
                  <time dateTime={t.created_at} className="text-subtle">{relativeTime(t.created_at)}</time>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
