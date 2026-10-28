import { Suspense } from "react";
import { RunWizard, RunWizardSkeleton } from "@/components/runs/run-wizard";

export default function Page() {
  return (
    <Suspense fallback={<RunWizardSkeleton />}>
      <RunWizard />
    </Suspense>
  );
}
