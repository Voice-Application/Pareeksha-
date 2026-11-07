import { KbDetail } from "@/components/rag/kb-detail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <KbDetail id={id} />;
}
