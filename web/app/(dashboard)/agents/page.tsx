import { Suspense } from "react";
import { AgentsList, AgentsListSkeleton } from "@/components/agents/agents-list";

export default function Page() {
  return (
    <Suspense fallback={<AgentsListSkeleton />}>
      <AgentsList />
    </Suspense>
  );
}
