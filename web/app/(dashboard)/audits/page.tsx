import { Suspense } from "react";
import { AuditsList } from "@/components/audits/audits-list";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <AuditsList />
    </Suspense>
  );
}
