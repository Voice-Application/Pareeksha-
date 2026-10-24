import { Suspense } from "react";
import { AgentForm } from "@/components/agents/agent-form";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <AgentForm agentId={id} />
    </Suspense>
  );
}
