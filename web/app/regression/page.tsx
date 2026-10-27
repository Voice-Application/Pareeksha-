import { Suspense } from "react";
import { RegressionPage } from "@/components/regression/regression-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <RegressionPage />
    </Suspense>
  );
}
