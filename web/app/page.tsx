import { Suspense } from "react";
import { Overview, OverviewSkeleton } from "@/components/overview/overview";

export default function OverviewPage() {
  return (
    <Suspense fallback={<OverviewSkeleton />}>
      <Overview />
    </Suspense>
  );
}
