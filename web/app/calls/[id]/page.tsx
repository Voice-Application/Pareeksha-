import { Suspense } from "react";
import { CallDetail, CallDetailSkeleton } from "@/components/calls/call-detail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<CallDetailSkeleton />}>
      <CallDetail callId={id} />
    </Suspense>
  );
}
