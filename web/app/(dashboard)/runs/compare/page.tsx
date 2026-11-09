import { Suspense } from "react";
import { RunCompare, RunCompareSkeleton } from "@/components/runs/run-compare";

export default function Page() {
  return (
    <Suspense fallback={<RunCompareSkeleton />}>
      <RunCompare />
    </Suspense>
  );
}
