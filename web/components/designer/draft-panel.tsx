"use client";

import Link from "next/link";
import { X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { Panel } from "@/components/ui/layout";
import { Button, LinkButton } from "@/components/ui/button";
import { FieldError, TextField } from "@/components/ui/field";
import type { Committed, Draft } from "./types";

const count = (n: number) => n.toLocaleString("en-IN");

function Group({
  title,
  n,
  children,
}: {
  title: string;
  n?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-border py-4 first:border-0 first:pt-0">
      <h3 className="mb-2 text-sm font-medium">
        {title}
        {n !== undefined && (
          <span className="num ml-2 font-normal text-muted">{n}</span>
        )}
      </h3>
      {children}
    </section>
  );
}

/** The draft assembling beside the chat, ending in the call count and the one primary action. */
export function DraftPanel({
  draft,
  committed,
  creating,
  locked,
  error,
  onEndpoint,
  onRemoveScenario,
  onCreate,
}: {
  draft: Draft | null;
  committed: Committed | null;
  creating: boolean;
  /** A chat request is in flight; edits would be lost when its draft arrives. */
  locked: boolean;
  /** 409 / 422 from commit, shown at the offending field. */
  error: { field: "name" | "endpoint" | "other"; message: string } | null;
  onEndpoint: (v: string) => void;
  onRemoveScenario: (i: number) => void;
  onCreate: () => void;
}) {
  const personas = useQuery({
    queryKey: ["personas", "designer"],
    queryFn: () =>
      call(api.GET("/api/v1/personas", { params: { query: { limit: 200 } } })),
  });
  const lines = useQuery({
    queryKey: ["noise", "designer"],
    queryFn: () =>
      call(
        api.GET("/api/v1/noise-profiles", {
          params: { query: { limit: 200 } },
        }),
      ),
  });

  if (!draft) {
    return (
      <Panel title="Draft">
        <p className="text-sm text-muted">
          Nothing drafted yet. Once the assistant has read your prompt, this
          column fills with the agent (languages, endpoint, disclosures,
          expected tools), its scenarios, the callers and the phone lines, and
          ends with the number of calls they make.
        </p>
      </Panel>
    );
  }

  const a = draft.agent;
  const s = draft.scenarios.length;
  const p = draft.personas.length;
  const l = draft.noise_profile_ids.length;
  const endpointMissing = !a.endpoint_url?.trim();
  const personaName = (x: Draft["personas"][number]) =>
    "new" in x
      ? x.new.name
      : (personas.data?.items.find((i) => i.id === x.existing_id)?.name ??
        (personas.isError ? x.existing_id : "Library persona"));
  const lineName = (id: string) =>
    lines.data?.items.find((i) => i.id === id)?.name ??
    (lines.isError ? id : "Library phone line");
  const namesFailed = personas.isError || lines.isError;

  if (committed) {
    return (
      <Panel title="Created">
        <div role="status" className="flex flex-col gap-4">
          <p className="text-base">
            Created agent{" "}
            <span className="font-medium">{committed.agent_name}</span>,{" "}
            {committed.scenario_ids.length} scenarios, {committed.new_personas}{" "}
            new callers and {committed.noise_profile_ids.length} phone lines.
            That is <span className="num">{count(committed.calls)}</span> calls.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <LinkButton variant="primary" href={committed.run_wizard_path}>
              Start run
            </LinkButton>
            <Link
              href={`/agents/${committed.agent_id}`}
              className="text-sm text-accent-fg underline underline-offset-2 hover:no-underline"
            >
              Open the agent
            </Link>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel
      title="Draft"
      aux={<span className="num">{count(s * p * l)} calls</span>}
    >
      {namesFailed && (
        <p
          role="alert"
          className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted"
        >
          Names unavailable, showing ids.
          <Button
            variant="ghost"
            onClick={() => {
              void personas.refetch();
              void lines.refetch();
            }}
          >
            Retry
          </Button>
        </p>
      )}
      <Group title="Agent">
        <dl className="mb-3 grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted">Name</dt>
          <dd className="break-words">{a.name}</dd>
          <dt className="text-muted">Languages</dt>
          <dd>{(a.languages ?? []).join(", ") || "none yet"}</dd>
          <dt className="text-muted">Disclosures</dt>
          <dd>
            {(a.mandatory_disclosures ?? []).map((d) => d.id).join(", ") ||
              "none"}
          </dd>
          <dt className="text-muted">Expected tools</dt>
          <dd className="mono text-xs leading-5">
            {(a.expected_tools ?? []).map((t) => t.name).join(", ") || "none"}
          </dd>
        </dl>
        {error?.field === "name" && (
          <div className="mb-3">
            <FieldError>{error.message}</FieldError>
          </div>
        )}
        <TextField
          label="Endpoint URL"
          required
          value={a.endpoint_url ?? ""}
          onChange={(e) => onEndpoint(e.target.value)}
          placeholder="ws://your-bot:8765/ws"
          spellCheck={false}
          className="mono"
          help={
            endpointMissing
              ? "Missing. The assistant could not work this out from the prompt."
              : undefined
          }
          disabled={locked}
          error={error?.field === "endpoint" ? error.message : null}
        />
      </Group>

      <Group title="Scenarios" n={s}>
        {s === 0 ? (
          <p className="text-sm text-muted">
            None left. Ask the assistant for more.
          </p>
        ) : (
          <ul className="flex flex-col">
            {draft.scenarios.map((x, i) => (
              <li
                key={i}
                className="flex items-start justify-between gap-2 py-1 text-sm"
              >
                <span className="min-w-0">
                  {x.title}
                  {(x.tags ?? []).length > 0 && (
                    <span className="ml-2 text-xs text-muted">
                      {(x.tags ?? []).join(", ")}
                    </span>
                  )}
                </span>
                <Button
                  icon
                  variant="ghost"
                  aria-label={`Remove scenario ${x.title}`}
                  disabled={locked || s <= 1}
                  title={
                    s <= 1
                      ? "A draft needs at least one scenario."
                      : locked
                        ? "Wait for the assistant to answer."
                        : undefined
                  }
                  onClick={() => onRemoveScenario(i)}
                >
                  <X size={14} aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Group>

      <Group title="Callers" n={p}>
        <ul className="flex flex-col gap-1 text-sm">
          {draft.personas.map((x, i) => (
            <li key={i}>
              {personaName(x)}{" "}
              <span className="text-xs text-muted">
                {"new" in x ? "new" : "from library"}
              </span>
            </li>
          ))}
        </ul>
      </Group>

      <Group title="Phone lines" n={l}>
        <ul className="flex flex-col gap-1 text-sm">
          {draft.noise_profile_ids.map((id) => (
            <li key={id}>{lineName(id)}</li>
          ))}
        </ul>
      </Group>

      <div className="mt-2 flex flex-col gap-2 border-t border-border pt-4">
        <p className="num text-sm">
          {s} × {p} × {l} ={" "}
          <span className="font-medium">{count(s * p * l)}</span> calls
        </p>
        {error?.field === "other" && <FieldError>{error.message}</FieldError>}
        <div>
          <Button
            variant="primary"
            loading={creating}
            disabled={
              locked || endpointMissing || s === 0 || p === 0 || l === 0
            }
            onClick={onCreate}
          >
            Create all
          </Button>
        </div>
        {locked ? (
          <p className="text-xs text-subtle">
            Editing is paused while the assistant answers.
          </p>
        ) : endpointMissing ? (
          <p className="text-xs text-subtle">
            Set the endpoint URL to create the agent.
          </p>
        ) : s === 0 || p === 0 || l === 0 ? (
          <p className="text-xs text-subtle">
            Needs at least one scenario, caller and phone line.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
