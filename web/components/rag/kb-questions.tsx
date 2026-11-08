"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Sparkles } from "lucide-react";
import {
  QUESTION_CSV_COLUMNS,
  UNMATCHED_REASONS,
  generateQuestions,
  getScenarioDraft,
  importQuestions,
  listDocuments,
  listQuestionScenarios,
  pct,
  questionErrorMessage,
  saveQuestionDrafts,
  type QuestionDraft,
  type QuestionImportResult,
  type QuestionUnmatched,
  type ScenarioRead,
} from "@/lib/api/rag";
import { useAgentOptions } from "@/lib/hooks/use-agents";
import { cn } from "@/lib/utils";
import { Chip, Panel } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Field, NumberField, SelectField, SliderField, controlClass } from "@/components/ui/field";
import { ConfirmDialog, Sheet } from "@/components/ui/overlay";
import { ErrorPanel, Skeleton, Strip, TableSkeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;

/** One CSV cell, quoted when it holds a comma, quote or line break. */
function csvCell(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

/** A two-row example of the import format: one answerable question (from `docName` when the KB has a document) and one the KB does not answer. */
export function exampleCsv(docName?: string): string {
  const rows = [
    [...QUESTION_CSV_COLUMNS],
    ["What is the late fee for a missed EMI?", "2 percent of the EMI amount.", docName ?? "loan-policy.pdf", "The late fee is 2 percent of the EMI amount."],
    ["Can I pay my EMI in cryptocurrency?", "", "", ""],
  ];
  return rows.map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000); // after the browser has started the download
}

/** Type chip for a question: answerable ones have a source passage, unanswerable ones expect "I don't know". */
function KindChip({ answerable }: { answerable: boolean }) {
  return <Chip>{answerable ? "answerable" : "unanswerable"}</Chip>;
}

/**
 * Poll a generation draft, then review it: every question starts selected, untick to drop, save the rest as scenarios.
 * Closing with unsaved drafts asks first; closing while pending just stops watching (nothing is saved).
 */
function ReviewSheet({ draftId, count, docName, onClose }: { draftId: string; count: number; docName: (id?: string | null) => string | undefined; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const [confirmClose, setConfirmClose] = useState(false);
  const poll = useQuery({
    queryKey: ["scenario-draft", draftId],
    queryFn: () => getScenarioDraft(draftId),
    refetchInterval: (q) => (q.state.data?.status === "pending" || !q.state.data ? 1500 : false),
    retry: 2,
  });
  const status = poll.data?.status;
  const drafts = (status === "ready" ? (poll.data?.drafts ?? []) : []) as QuestionDraft[];
  const request = poll.data?.request;
  const unmatched = request && "kind" in request && request.kind === "rag" ? (request.unmatched ?? 0) : 0;
  const keep = drafts.filter((_, i) => !dropped.has(i));

  const save = useMutation({
    mutationFn: () => saveQuestionDrafts(keep),
    onSuccess: (r) => {
      toast(`Saved ${plural(r.items.length, "question", "questions")}.`);
      void qc.invalidateQueries({ queryKey: ["scenarios"] });
      onClose();
    },
  });

  function requestClose() {
    if (status === "ready" && drafts.length > 0 && !save.isSuccess) setConfirmClose(true);
    else onClose();
  }

  return (
    <>
      <Sheet
        open
        onClose={requestClose}
        title="Review generated questions"
        wide
        footer={
          status === "ready" ? (
            <div className="flex items-center justify-between gap-2">
              <Button variant="ghost" onClick={requestClose}>
                Discard
              </Button>
              <Button variant="primary" disabled={keep.length === 0} loading={save.isPending} onClick={() => save.mutate()}>
                Save {keep.length} selected
              </Button>
            </div>
          ) : undefined
        }
      >
        {(status === undefined || status === "pending") && (
          <div className="grid gap-3" role="status" aria-live="polite">
            <p className="text-sm">
              Generating <span className="mono">{count}</span> questions from the documents. This takes a short while.
            </p>
            {Array.from({ length: Math.min(count, 4) }, (_, i) => (
              <div key={i} className="rounded-md border border-border p-3">
                <Skeleton className="mb-2 h-4 w-1/2" />
                <Skeleton className="h-3 w-full" />
              </div>
            ))}
            {poll.isError && (
              <Strip tone="error" onRetry={() => void poll.refetch()}>
                Could not check progress. {questionErrorMessage(poll.error)}
              </Strip>
            )}
          </div>
        )}
        {status === "failed" && (
          <div className="grid gap-3">
            <Strip tone="error">Generation failed. {poll.data?.error ?? "The generator could not produce questions."}</Strip>
            <div>
              <Button onClick={onClose}>Close</Button>
            </div>
          </div>
        )}
        {status === "ready" && (
          <div className="grid gap-3">
            {drafts.length < count && (
              <Strip tone="warn">
                <span className="mono">{drafts.length}</span> of <span className="mono">{count}</span> questions passed the checks.
                {unmatched > 0 && <> {plural(unmatched, "was", "were")} dropped because the quote was not found in the document.</>}
              </Strip>
            )}
            {drafts.length === 0 && <p className="text-sm text-muted">No usable questions came back. Close this and try again.</p>}
            {save.isError && (
              <Strip tone="error" onRetry={() => save.mutate()}>
                Could not save. {questionErrorMessage(save.error)}
              </Strip>
            )}
            <ul className="grid gap-3" aria-label="Generated questions">
              {drafts.map((d, i) => {
                const exp = d.rag_expectation;
                const answerable = exp?.answerable ?? true;
                return (
                  <li key={i} className="rounded-md border border-border bg-surface p-3">
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        aria-label={`Keep question: ${d.title}`}
                        checked={!dropped.has(i)}
                        onChange={(e) =>
                          setDropped((s) => {
                            const n = new Set(s);
                            if (e.target.checked) n.delete(i);
                            else n.add(i);
                            return n;
                          })
                        }
                        className="mt-1 h-4 w-4"
                        style={{ accentColor: "var(--accent)" }}
                      />
                      <span className="grid min-w-0 flex-1 gap-1">
                        <span className="font-medium">{d.title}</span>
                        <span className="flex flex-wrap items-center gap-2 text-xs text-muted">
                          <KindChip answerable={answerable} />
                          {answerable ? <span className="mono break-all">{docName(exp?.source_document_id) ?? "unknown document"}</span> : <span>not in the knowledge base</span>}
                        </span>
                        {exp?.reference_answer && (
                          <span className="text-sm">
                            <span className="text-subtle">Expected answer: </span>
                            {exp.reference_answer}
                          </span>
                        )}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Sheet>
      <ConfirmDialog
        open={confirmClose}
        onClose={() => setConfirmClose(false)}
        title="Discard generated questions?"
        body="The questions have not been saved. Closing now discards them."
        confirmLabel="Discard questions"
        onConfirm={() => {
          setConfirmClose(false);
          onClose();
        }}
      />
    </>
  );
}

/** Count and unanswerable share, validated here; the review sheet opens once the API accepts the request. */
function GenerateForm({ kbId, agentId, requireAgent, blocked, docName }: { kbId: string; agentId: string; requireAgent: () => boolean; blocked: string | null; docName: (id?: string | null) => string | undefined }) {
  const [count, setCount] = useState("10");
  const [share, setShare] = useState(0.2);
  const [countError, setCountError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ id: string; count: number } | null>(null);
  const start = useMutation({
    mutationFn: (n: number) => generateQuestions(kbId, { agent_id: agentId, count: n, unanswerable_share: share }),
    onSuccess: (r, n) => setDraft({ id: r.draft_id, count: n }),
  });

  function submit(ev: FormEvent) {
    ev.preventDefault();
    start.reset();
    const n = Number(count);
    const bad = !Number.isInteger(n) || n < 1 || n > 50;
    setCountError(bad ? "Use a whole number from 1 to 50." : null);
    if (!requireAgent()) return;
    if (bad) return void requestAnimationFrame(() => document.getElementById("q-count")?.focus());
    start.mutate(n);
  }

  return (
    <>
    <form onSubmit={submit} noValidate aria-label="Generate questions" className="grid content-start gap-4 rounded-sm bg-canvas p-4">
      <div>
        <h3 className="text-sm font-medium">Generate with AI</h3>
        <p className="mt-1 text-sm text-muted">The platform LLM writes questions from passages of the documents, and each quote is checked against its document. You review them before anything is saved.</p>
      </div>
      <NumberField id="q-count" label="How many" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} error={countError} fieldClassName="max-w-[160px]" help="1 to 50." />
      <SliderField label="Unanswerable share" min={0} max={1} step={0.05} value={share} onChange={setShare} format={(v) => pct(v)} help="Questions the documents do not answer. They catch an agent that makes things up." />
      {start.isError && <Strip tone="error">Could not start generation. {questionErrorMessage(start.error)}</Strip>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" loading={start.isPending} disabled={!!blocked}>
          <Sparkles size={14} strokeWidth={1.6} aria-hidden />
          Generate questions
        </Button>
        {blocked && <span className="text-xs text-subtle">{blocked}</span>}
      </div>
    </form>
    {draft && <ReviewSheet key={draft.id} draftId={draft.id} count={draft.count} docName={docName} onClose={() => setDraft(null)} />}
    </>
  );
}

const unmatchedColumns: Column<QuestionUnmatched>[] = [
  {
    key: "row",
    header: "Row",
    cell: (u) => (
      <span className="whitespace-nowrap">
        <span className="num">{u.row}</span> <span className="text-xs text-subtle">(line {u.row + 1} of the file)</span>
      </span>
    ),
  },
  {
    key: "reason",
    header: "Why it was skipped",
    cell: (u) => (
      <span className="grid gap-0.5">
        <span>{UNMATCHED_REASONS[u.reason] ?? u.reason}</span>
        <span className="mono text-2xs text-subtle">{u.reason}</span>
      </span>
    ),
  },
];

/** CSV picker with the column template and an example download; shows the created count and every skipped row with its reason. */
function ImportForm({ kbId, agentId, requireAgent, exampleDoc }: { kbId: string; agentId: string; requireAgent: () => boolean; exampleDoc?: string }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [result, setResult] = useState<QuestionImportResult | null>(null);
  const run = useMutation({
    mutationFn: (f: File) => importQuestions(kbId, agentId, f),
    onSuccess: (r) => {
      setResult(r);
      setFile(null);
      if (input.current) input.current.value = "";
      if (r.created > 0) void qc.invalidateQueries({ queryKey: ["scenarios"] });
    },
  });

  function submit(ev: FormEvent) {
    ev.preventDefault();
    run.reset();
    setResult(null);
    setFileError(file ? null : "Choose a CSV file.");
    if (!requireAgent()) return;
    if (!file) return void requestAnimationFrame(() => input.current?.focus());
    run.mutate(file);
  }

  return (
    <form onSubmit={submit} noValidate aria-label="Import questions" className="grid content-start gap-4 rounded-sm bg-canvas p-4">
      <div>
        <h3 className="text-sm font-medium">Import CSV</h3>
        <p className="mt-1 text-sm text-muted">Your own questions with known answers. Pareeksha finds each quote in its document and stores where it is.</p>
      </div>
      <div className="grid gap-2 text-sm">
        <p className="text-muted">The first row names these four columns:</p>
        <ul className="grid gap-1" aria-label="CSV columns">
          <li>
            <code className="mono">question</code> <span className="text-muted">what the caller asks</span>
          </li>
          <li>
            <code className="mono">expected_answer</code> <span className="text-muted">the answer you expect</span>
          </li>
          <li>
            <code className="mono">source_document</code> <span className="text-muted">the file name of a document above</span>
          </li>
          <li>
            <code className="mono">source_quote</code> <span className="text-muted">text copied from that document. Leave it empty when the knowledge base does not answer the question.</span>
          </li>
        </ul>
        <div>
          <Button variant="ghost" className="-ml-3" onClick={() => downloadText("questions-example.csv", exampleCsv(exampleDoc))}>
            <Download size={14} strokeWidth={1.6} aria-hidden />
            Download example CSV
          </Button>
        </div>
      </div>
      <Field label="CSV file" id="q-file" error={fileError} help="UTF-8, up to 1,000 rows and 10 MB.">
        <input
          ref={input}
          id="q-file"
          type="file"
          accept=".csv,text/csv"
          aria-invalid={fileError ? true : undefined}
          aria-describedby={fileError ? "q-file-error" : "q-file-help"}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setFileError(null);
          }}
          className={cn(controlClass, "h-auto py-1.5 file:mr-3 file:rounded-xs file:border-0 file:bg-sunken file:px-2 file:py-0.5 file:text-sm")}
        />
      </Field>
      {run.isError && <Strip tone="error">Could not import. {questionErrorMessage(run.error)}</Strip>}
      <div>
        <Button type="submit" variant="primary" loading={run.isPending}>
          <FileUp size={14} strokeWidth={1.6} aria-hidden />
          Import questions
        </Button>
      </div>
      {result && (
        <div className="grid gap-3">
          <p role="status" className="text-sm">
            <span className="font-medium">{plural(result.created, "question", "questions")} created.</span>
            {result.unmatched.length > 0 && <> {plural(result.unmatched.length, "row was", "rows were")} skipped.</>}
          </p>
          {result.unmatched.length > 0 && <DataTable caption="Skipped rows" columns={unmatchedColumns} rows={result.unmatched} rowKey={(u) => String(u.row)} sort={null} onSort={() => undefined} />}
        </div>
      )}
    </form>
  );
}

/**
 * The knowledge base's ground-truth questions: generate or import them for a prompt agent, and list the saved ones.
 * The scenarios API has no knowledge-base filter, so the list is the `rag` scenarios whose source document is in this
 * knowledge base, plus every unanswerable one (those have no source document to match on).
 */
export function KbQuestions({ kbId, localOnly }: { kbId: string; localOnly: boolean }) {
  const agents = useAgentOptions();
  const docs = useQuery({ queryKey: ["kb-docs", kbId], queryFn: () => listDocuments(kbId), select: (p) => p.items ?? [] });
  const questions = useQuery({ queryKey: ["scenarios", "rag-questions"], queryFn: listQuestionScenarios });
  const promptAgents = (agents.data ?? []).filter((a) => a.adapter === "prompt" && !a.archived);
  const [picked, setPicked] = useState("");
  const [agentError, setAgentError] = useState<string | null>(null);
  const agentId = picked || promptAgents[0]?.id || "";

  const docNames = useMemo(() => new Map((docs.data ?? []).map((d) => [d.id, d.filename])), [docs.data]);
  const docName = (id?: string | null) => (id ? docNames.get(id) : undefined);
  const agentNames = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
  const rows = (questions.data ?? []).filter((s) => s.rag_expectation && (!s.rag_expectation.answerable || docNames.has(s.rag_expectation.source_document_id ?? "")));
  const anyUnanswerable = rows.some((s) => !s.rag_expectation?.answerable);
  const hasDocs = (docs.data?.length ?? 0) > 0;
  const blocked = localOnly ? "This knowledge base is local only, so the platform LLM may not read it. Import a CSV instead." : docs.isSuccess && !hasDocs ? "Upload a document first." : null;

  /** False (and the select flagged and focused) when no prompt agent is chosen. */
  function requireAgent(): boolean {
    if (agentId) {
      setAgentError(null);
      return true;
    }
    setAgentError("Choose a prompt agent.");
    requestAnimationFrame(() => document.getElementById("q-agent")?.focus());
    return false;
  }

  const columns: Column<ScenarioRead>[] = [
    {
      key: "question",
      header: "Question",
      cell: (s) => (
        <span className="grid gap-0.5">
          <span className="font-medium">{s.title}</span>
          {s.rag_expectation?.reference_answer && <span className="line-clamp-2 text-xs text-muted">{s.rag_expectation.reference_answer}</span>}
        </span>
      ),
    },
    { key: "kind", header: "Type", cell: (s) => <KindChip answerable={s.rag_expectation?.answerable ?? true} /> },
    {
      key: "source",
      header: "Source document",
      cell: (s) => (s.rag_expectation?.answerable ? <span className="mono break-all">{docName(s.rag_expectation.source_document_id)}</span> : <span className="text-subtle">none</span>),
    },
    { key: "agent", header: "Agent", hidePhone: true, cell: (s) => <span className="text-muted">{s.agent_id ? (agentNames.get(s.agent_id) ?? "archived agent") : "any agent"}</span> },
  ];

  return (
    <Panel title="Questions" bodyClassName="grid gap-5" aux={questions.isSuccess && docs.isSuccess ? <span className="num">{rows.length}</span> : null}>
      <p className="max-w-[68ch] text-sm text-muted">
        Questions with a known answer and source passage. The RAG lab scores retrieval against them. They are saved as scenarios tagged <code className="mono">rag</code> for the agent you choose.
      </p>
      <SelectField
        id="q-agent"
        label="Prompt agent"
        fieldClassName="max-w-[360px]"
        value={agentId}
        error={agentError}
        onChange={(e) => {
          setPicked(e.target.value);
          setAgentError(null);
        }}
        help={agents.isSuccess && promptAgents.length === 0 ? "No prompt agents yet. Create one under Agents first." : "Generated and imported questions are saved for this agent."}
      >
        {agents.isPending && <option value="">Loading agents</option>}
        {agents.isSuccess && promptAgents.length === 0 && <option value="">No prompt agents</option>}
        {promptAgents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </SelectField>
      {agents.isError && <ErrorPanel error={agents.error} what="agents" onRetry={() => void agents.refetch()} />}
      <div className="grid gap-4 min-[900px]:grid-cols-2">
        <GenerateForm kbId={kbId} agentId={agentId} requireAgent={requireAgent} blocked={blocked} docName={docName} />
        <ImportForm kbId={kbId} agentId={agentId} requireAgent={requireAgent} exampleDoc={docs.data?.[0]?.filename} />
      </div>

      {(questions.isPending || docs.isPending) && <TableSkeleton rows={3} label="Loading questions" />}
      {questions.isError && <ErrorPanel error={questions.error} what="questions" onRetry={() => void questions.refetch()} />}
      {docs.isError && <ErrorPanel error={docs.error} what="the documents the questions point at" onRetry={() => void docs.refetch()} />}
      {questions.isSuccess && docs.isSuccess && rows.length === 0 && <p className="text-sm text-muted">No questions for this knowledge base yet. Generate some or import a CSV.</p>}
      {questions.isSuccess && docs.isSuccess && rows.length > 0 && (
        <div className="grid gap-2">
          <DataTable caption="Questions" columns={columns} rows={rows} rowKey={(s) => s.id} sort={null} onSort={() => undefined} />
          {anyUnanswerable && <p className="text-xs text-subtle">Unanswerable questions have no source document, so Pareeksha cannot tell which knowledge base they were written for. All of them are listed here.</p>}
        </div>
      )}
    </Panel>
  );
}
