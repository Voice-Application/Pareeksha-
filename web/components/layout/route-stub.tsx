/** Body for routes reachable from the sidebar whose page is implemented by a later FE task. */
export function RouteStub({ title }: { title: string }) {
  return (
    <section>
      <h1 className="text-lg">{title}</h1>
      <p className="text-sm text-muted">This page is not implemented yet.</p>
    </section>
  );
}
