import { DialectReport } from "@/components/dialect/dialect-pages";

export default async function Page({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return <DialectReport id={reportId} />;
}
