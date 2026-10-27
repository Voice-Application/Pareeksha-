import { Suspense } from "react";
import { RunDetail, RunDetailSkeleton } from "@/components/runs/run-detail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<RunDetailSkeleton />}>
      <RunDetail runId={id} />
    </Suspense>
  );
}
