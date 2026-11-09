import { Suspense } from "react";
import { ScenariosList, ScenariosListSkeleton } from "@/components/scenarios/scenarios-list";

export default function Page() {
  return (
    <Suspense fallback={<ScenariosListSkeleton />}>
      <ScenariosList />
    </Suspense>
  );
}
