/**
 * In-memory sign-in throttle (one server process only). Failures count per account (normalised email), so
 * rotating a client header does not help against one account, and, behind a trusted proxy, per client
 * address across accounts. Entries expire after the window; the map is pruned on write and capped.
 */
const WINDOW_MS = 10 * 60_000;
export const ACCOUNT_LIMIT = 5;
export const CLIENT_LIMIT = 25;
export const MAX_ENTRIES = 10_000;

export type Limiter = { locked(key: string): boolean; fail(key: string): void; clear(key: string): void; size(): number };

export function createLimiter(limit: number, opts: { windowMs?: number; maxEntries?: number; now?: () => number } = {}): Limiter {
  const { windowMs = WINDOW_MS, maxEntries = MAX_ENTRIES, now = Date.now } = opts;
  const entries = new Map<string, { n: number; until: number }>();
  return {
    locked: (key) => {
      const e = entries.get(key);
      return !!e && e.n >= limit && e.until > now();
    },
    fail: (key) => {
      const t = now();
      const e = entries.get(key);
      entries.delete(key); // re-insert so Map order stays oldest-first for eviction
      for (const [k, v] of entries) if (v.until <= t) entries.delete(k);
      while (entries.size >= maxEntries) entries.delete(entries.keys().next().value!);
      entries.set(key, { n: e && e.until > t ? e.n + 1 : 1, until: t + windowMs });
    },
    clear: (key) => void entries.delete(key),
    size: () => entries.size,
  };
}

/**
 * The client address, only when TRUST_PROXY_HEADERS=1 says a reverse proxy we control sets X-Forwarded-For
 * (default off: anyone can send that header). Next.js route handlers do not expose the socket address.
 */
export function clientAddress(headers: Headers, trust = process.env.TRUST_PROXY_HEADERS === "1"): string | null {
  if (!trust) return null;
  return headers.get("x-forwarded-for")?.split(",")[0].trim() || null;
}

const accounts = createLimiter(ACCOUNT_LIMIT);
const clients = createLimiter(CLIENT_LIMIT);

export function loginLocked(email: string, client: string | null): boolean {
  return accounts.locked(email) || (client !== null && clients.locked(client));
}
export function noteLoginFailure(email: string, client: string | null): void {
  accounts.fail(email);
  if (client !== null) clients.fail(client);
}
/** A successful sign-in resets its account only; the client count keeps limiting spraying across accounts. */
export function clearLoginFailures(email: string): void {
  accounts.clear(email);
}
