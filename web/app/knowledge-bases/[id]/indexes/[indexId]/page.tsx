import { ChunkBrowser } from "@/components/rag/chunk-browser";

export default async function Page({ params }: { params: Promise<{ id: string; indexId: string }> }) {
  const { id, indexId } = await params;
  return <ChunkBrowser kbId={id} indexId={indexId} />;
}
