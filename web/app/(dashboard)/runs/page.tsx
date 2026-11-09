import { Suspense } from "react";
import { RunsList, RunsListSkeleton } from "@/components/runs/runs-list";

export default function Page() {
  return (
    <Suspense fallback={<RunsListSkeleton />}>
      <RunsList />
    </Suspense>
  );
}
