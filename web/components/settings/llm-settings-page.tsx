"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import type { components } from "@/lib/api/schema";
import { PageHeader } from "@/components/ui/layout";
import { Button } from "@/components/ui/button";
import { Segmented, TextField } from "@/components/ui/field";
import { ErrorPanel, FormSkeleton, Strip } from "@/components/ui/states";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { useRole } from "@/components/layout/theme-toggle";

type Settings = components["schemas"]["LLMSettingsOut"];
type Provider = Settings["provider"];
type TestResult = components["schemas"]["LLMTestResult"];

const PROVIDERS: { value: Provider; label: string }[] = [
  { value: "deepseek", label: "DeepSeek" },
  { value: "gemini", label: "Gemini" },
  { value: "openai_compatible", label: "OpenAI-compatible" },
];
const KEY = ["settings", "llm"];

function SettingsForm({ data, readOnly }: { data: Settings; readOnly: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [provider, setProvider] = useState<Provider>(data.provider);
  const [baseUrl, setBaseUrl] = useState(data.base_url ?? "");
  const [judge, setJudge] = useState(data.judge_model ?? "");
  const [caller, setCaller] = useState(data.caller_model ?? "");
  const [designer, setDesigner] = useState(data.designer_model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [revertOpen, setRevertOpen] = useState(false);
  const compat = provider === "openai_compatible";
  const dirty =
    provider !== data.provider ||
    (compat && baseUrl !== (data.base_url ?? "")) ||
    judge !== (data.judge_model ?? "") ||
    caller !== (data.caller_model ?? "") ||
    designer !== (data.designer_model ?? "") ||
    apiKey !== "";
  const showKeyInput = !data.api_key_set || replacing;

  const save = useMutation({
    mutationFn: () =>
      call(
        api.PUT("/api/v1/settings/llm", {
          body: {
            provider,
            base_url: compat ? baseUrl.trim() || null : null,
            judge_model: judge.trim() || null,
            caller_model: caller.trim() || null,
            designer_model: designer.trim() || null,
            ...(apiKey ? { api_key: apiKey } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setApiKey("");
      setReplacing(false);
      setErr(null);
      setTest(null);
      toast("Saved LLM settings.");
      void qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (e) => setErr(e instanceof ApiError ? e.userMessage() : "The request failed."),
  });

  const revert = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/settings/llm")),
    onSuccess: () => {
      setRevertOpen(false);
      toast("Reverted to environment defaults.");
      void qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (e) => {
      setRevertOpen(false);
      setErr(e instanceof ApiError ? e.userMessage() : "The request failed.");
    },
  });

  const run = useMutation({
    mutationFn: () => call(api.POST("/api/v1/settings/llm/test")),
    onSuccess: setTest,
    onError: (e) => setTest({ ok: false, provider, model: "", latency_ms: 0, error: e instanceof ApiError ? e.userMessage() : "The request failed." }),
  });

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!readOnly) save.mutate();
      }}
    >
      <p className="text-sm text-muted">{data.source === "project" ? "Project setting" : "Using environment defaults (.env)"}</p>
      {readOnly && <Strip tone="warn">Only an admin key can change LLM settings. You are viewing the current values.</Strip>}
      {err && <Strip tone="error">{err}</Strip>}

      <Segmented label="Provider" value={provider} onChange={setProvider} options={PROVIDERS} disabled={readOnly} />
      {compat && (
        <TextField label="Base URL" type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" help="https only. Required for OpenAI-compatible." disabled={readOnly} className="mono" />
      )}
      <TextField label="Judge model" value={judge} onChange={(e) => setJudge(e.target.value)} placeholder={data.judge_model ?? ""} disabled={readOnly} className="mono" />
      <TextField label="Caller model" value={caller} onChange={(e) => setCaller(e.target.value)} placeholder={data.caller_model ?? ""} disabled={readOnly} className="mono" />
      <TextField label="Designer model" value={designer} onChange={(e) => setDesigner(e.target.value)} placeholder={data.designer_model ?? ""} help="Defaults to the judge model." disabled={readOnly} className="mono" />

      {showKeyInput ? (
        <TextField label="API key" type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} help="Write-only. Leave empty to keep the stored key." disabled={readOnly} />
      ) : (
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium">API key</span>
          <div className="flex items-center gap-3 text-sm">
            <span>
              Set, ends in <span className="mono">••••{data.api_key_last4}</span>
            </span>
            {!readOnly && (
              <Button onClick={() => setReplacing(true)} className="h-7 px-3">
                Replace
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {!readOnly && (
          <Button type="submit" variant="primary" loading={save.isPending}>
            Save
          </Button>
        )}
        <Button onClick={() => run.mutate()} loading={run.isPending} disabled={readOnly || dirty} aria-describedby="llm-test-hint">
          Test saved settings
        </Button>
        {dirty && !readOnly && (
          <span id="llm-test-hint" className="text-xs text-subtle">
            Save first to test these values
          </span>
        )}
        {!readOnly && data.source === "project" && (
          <Button variant="ghost" onClick={() => setRevertOpen(true)}>
            Revert to environment
          </Button>
        )}
      </div>

      <div aria-live="polite" className="text-sm">
        {test && !test.ok && (
          <p className="flex items-start gap-1 text-fail-fg">
            <CircleAlert size={14} strokeWidth={1.6} className="mt-0.5 shrink-0" aria-hidden />
            <span>{test.error ?? "Connection failed."}</span>
          </p>
        )}
        {test?.ok && (
          <p className="flex items-start gap-1">
            <CircleCheck size={14} strokeWidth={1.6} className="mt-0.5 shrink-0" aria-hidden />
            <span>
              Connected to <span className="mono">{test.model}</span> {typeof test.latency_ms === "number" && (
                <>
                  {" "}in <span className="mono">{test.latency_ms} ms</span>
                </>
              )}
              .
            </span>
          </p>
        )}
      </div>

      <ConfirmDialog
        open={revertOpen}
        onClose={() => setRevertOpen(false)}
        title="Revert to environment?"
        body="The project setting and its stored API key are removed. The .env defaults apply again."
        confirmLabel="Revert"
        busy={revert.isPending}
        onConfirm={() => revert.mutate()}
      />
    </form>
  );
}

export function LlmSettingsPage() {
  // Read-only for member sessions; access itself is enforced by the API (a 403 on save is shown inline).
  const readOnly = useRole() === "member";
  const q = useQuery({ queryKey: KEY, queryFn: () => call(api.GET("/api/v1/settings/llm")) });
  return (
    <div className="max-w-[640px]">
      <PageHeader title="AI settings" description="The AI key and models Pareeksha uses to run your prompts, play the customers and check the answers." />
      {q.isPending ? (
        <FormSkeleton sections={1} />
      ) : q.isError ? (
        <ErrorPanel error={q.error} what="LLM settings" onRetry={() => void q.refetch()} />
      ) : (
        <SettingsForm key={JSON.stringify(q.data)} data={q.data} readOnly={readOnly} />
      )}
    </div>
  );
}
