import { Suspense } from "react";
import { NoiseList, NoiseListSkeleton } from "@/components/noise/noise-list";

export default function Page() {
  return (
    <Suspense fallback={<NoiseListSkeleton />}>
      <NoiseList />
    </Suspense>
  );
}
