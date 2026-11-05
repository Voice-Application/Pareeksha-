/**
 * Signed session cookie for account sign-in. The token is `<base64url payload>.<hmac>`: the payload is the
 * user (id, name, email, role) and an expiry, the HMAC (SHA-256, keyed by SESSION_SECRET) covers the payload.
 * Rotating SESSION_SECRET signs everyone out. Web Crypto only, so it runs in proxy.ts and route handlers alike.
 * A disabled account stays signed in until its token expires, so the lifetime is short.
 */
export const SESSION_COOKIE = "pareeksha_session";
/** Not secret, readable by the page: holds the role so the shell can show Sign out and the Users link. Never trusted for access. */
export const SIGNED_IN_COOKIE = "pareeksha_signed_in";
export const SESSION_MAX_AGE_S = 12 * 60 * 60;

export type Role = "admin" | "member";
export type SessionUser = { id: string; name: string; email: string; role: Role };
type Payload = SessionUser & { exp: number };

const enc = new TextEncoder();
const dec = new TextDecoder();

const toB64u = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
const fromB64u = (s: string) => Uint8Array.from(atob(s.replaceAll("-", "+").replaceAll("_", "/")), (c) => c.charCodeAt(0));

/** SESSION_SECRET, or null when it is missing or too short to be a secret. */
export function sessionSecret(): string | null {
  const s = process.env.SESSION_SECRET;
  return s && s.length >= 16 ? s : null;
}

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return toB64u(new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(message))));
}

/** Constant-time string comparison (length is not secret here: both sides are digests). */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(secret: string, user: SessionUser, now = Date.now()): Promise<string> {
  const payload: Payload = { ...user, exp: Math.floor(now / 1000) + SESSION_MAX_AGE_S };
  const body = toB64u(enc.encode(JSON.stringify(payload)));
  return `${body}.${await hmac(secret, body)}`;
}

export async function verifySessionToken(secret: string, token: string | undefined, now = Date.now()): Promise<SessionUser | null> {
  if (!token) return null;
  const dot = token.indexOf(".");
  if (dot < 1) return null;
  const body = token.slice(0, dot);
  if (!safeEqual(token.slice(dot + 1), await hmac(secret, body))) return null;
  try {
    const p = JSON.parse(dec.decode(fromB64u(body))) as Payload;
    if (!Number.isInteger(p.exp) || p.exp * 1000 < now || (p.role !== "admin" && p.role !== "member") || typeof p.id !== "string") return null;
    return { id: p.id, name: String(p.name), email: String(p.email), role: p.role };
  } catch {
    return null;
  }
}

/** Only same-site paths are allowed as a post-login destination. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\") || next.startsWith("/login")) return "/";
  return next;
}
