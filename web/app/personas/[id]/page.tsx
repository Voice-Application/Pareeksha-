import { PersonaPage } from "@/components/personas/persona-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PersonaPage personaId={id === "new" ? undefined : id} />;
}
