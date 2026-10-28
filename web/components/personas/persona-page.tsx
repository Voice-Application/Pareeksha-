"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { PageHeader, Panel } from "@/components/ui/layout";
import { FormSkeleton, PageError } from "@/components/ui/states";
import { PersonaEditor } from "./persona-editor";

/** Deep link `/personas/[id]` (and `/personas/new`): same editor as the Sheet, on its own page. */
export function PersonaPage({ personaId }: { personaId?: string }) {
  const persona = useQuery({
    queryKey: ["persona", personaId],
    queryFn: () => call(api.GET("/api/v1/personas/{persona_id}", { params: { path: { persona_id: personaId! } } })),
    enabled: !!personaId,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });
  const others = useQuery({
    queryKey: ["personas", "all-for-voice-check"],
    queryFn: () => call(api.GET("/api/v1/personas", { params: { query: { limit: 200 } } })),
    select: (p) => p.items,
  });

  const crumb = (
    <>
      <Link href="/personas" className="text-accent-fg underline underline-offset-2">
        Personas
      </Link>{" "}
      / {personaId ? (persona.data?.name ?? "") : "New"}
    </>
  );

  if (personaId && persona.isPending) {
    return (
      <>
        <PageHeader eyebrow={crumb} title="Persona" />
        <FormSkeleton sections={3} />
      </>
    );
  }
  if (personaId && persona.isError) {
    return (
      <>
        <PageHeader eyebrow={crumb} title="Persona" />
        <PageError error={persona.error} onRetry={() => void persona.refetch()} backHref="/personas" backLabel="Back to personas" />
      </>
    );
  }
  return (
    <>
      <PageHeader eyebrow={crumb} title={persona.data?.name ?? "New persona"} description="Who is calling: language, code-mix, voice, mood and habits." />
      <div className="max-w-[560px]">
        <Panel>
          <PersonaEditor key={persona.data?.id ?? "new"} persona={persona.data} others={others.data ?? []} mode="page" />
        </Panel>
      </div>
    </>
  );
}
