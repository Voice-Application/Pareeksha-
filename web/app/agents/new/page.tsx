import { Suspense } from "react";
import { AgentForm } from "@/components/agents/agent-form";

export default function Page() {
  return (
    <Suspense>
      <AgentForm />
    </Suspense>
  );
}
