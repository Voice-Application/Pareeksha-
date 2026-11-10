import table from "./admin-routes.json";

/**
 * Which proxied requests need a signed-in admin. The BFF forwards every request with the server's admin
 * API key, so the role check for admin-scoped upstream routes has to happen here.
 */
const ROUTES = (table.routes as [string, string][]).map(([method, path]) => ({
  method,
  segs: path.split("/").filter(Boolean).map((s) => (s.startsWith("{") ? null : s)),
}));

/**
 * The proxy path as upstream routing could resolve it, without the optional `api/v1` prefix. Decoded
 * slashes are split (the proxy re-encodes them, and upstream may decode them again), empty segments are
 * dropped and case is folded, so `API-KEYS`, `api-keys/` or `api-keys%2F` cannot dodge the table.
 */
export function normalisePath(path: string[]): string[] {
  const segs = path.flatMap((s) => s.split("/")).filter(Boolean).map((s) => s.toLowerCase());
  return segs[0] === "api" && segs[1] === "v1" ? segs.slice(2) : segs;
}

export function requiresAdmin(method: string, path: string[]): boolean {
  const m = method.toUpperCase() === "HEAD" ? "GET" : method.toUpperCase();
  const segs = normalisePath(path);
  // BFF-only: user management, and the metrics summary (Kafka/outbox/DLQ depth) that the read scope would allow.
  if (segs[0] === "users" || segs[0] === "metrics") return true;
  return ROUTES.some((r) => r.method === m && r.segs.length === segs.length && r.segs.every((s, i) => s === null || s === segs[i]));
}
