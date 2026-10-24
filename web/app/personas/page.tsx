import { Suspense } from "react";
import { PersonasList, PersonasListSkeleton } from "@/components/personas/personas-list";

export default function Page() {
  return (
    <Suspense fallback={<PersonasListSkeleton />}>
      <PersonasList />
    </Suspense>
  );
}
