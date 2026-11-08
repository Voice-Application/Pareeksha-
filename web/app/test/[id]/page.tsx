import { QuickTestResult } from "@/components/quick/test-result";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuickTestResult id={id} />;
}
