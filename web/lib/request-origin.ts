/**
 * Cross-site request check for state-changing routes, on top of the SameSite=Lax session cookie (which
 * does not stop same-site sibling origins or every browser). Browsers send `Origin` on non-GET fetches and
 * form posts; older ones may only send `Sec-Fetch-Site`. A request with neither is not from a browser page,
 * so it cannot carry a victim's cookie cross-site and is allowed.
 */
export function isCrossSiteRequest(method: string, headers: Headers, ownHost: string): boolean {
  const m = method.toUpperCase();
  if (m === "GET" || m === "HEAD") return false;
  const origin = headers.get("origin");
  if (origin !== null) {
    try {
      const o = new URL(origin);
      // Normalise the host the same way (default port dropped, lower case) under the origin's scheme.
      return o.host !== new URL(`${o.protocol}//${ownHost}`).host;
    } catch {
      return true; // "null" (sandboxed frame, privacy redirect) or garbage
    }
  }
  return headers.get("sec-fetch-site") === "cross-site";
}
