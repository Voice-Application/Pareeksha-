import { NoisePage } from "@/components/noise/noise-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <NoisePage profileId={id === "new" ? undefined : id} />;
}
