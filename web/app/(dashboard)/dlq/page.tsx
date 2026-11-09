import { Suspense } from "react";
import { DlqPage } from "@/components/ops/dlq-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <DlqPage />
    </Suspense>
  );
}
