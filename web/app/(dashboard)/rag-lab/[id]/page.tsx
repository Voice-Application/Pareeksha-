import { RagReportView } from "@/components/rag/report";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RagReportView id={id} />;
}
