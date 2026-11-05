/**
 * Signed session cookie for the optional WEB_PASSWORD gate. The token is `<expiry>.<hmac>`, where the HMAC
 * (SHA-256, keyed by WEB_PASSWORD) covers the expiry. Changing the password invalidates every session.
 * Uses Web Crypto only, so it runs in proxy.ts and in route handlers alike.
 */
export const SESSION_COOKIE = "pareeksha_session";
/** Not secret, readable by the page: tells the shell to show Sign out. Never trusted for access. */
export const SIGNED_IN_COOKIE = "pareeksha_signed_in";
export const SESSION_MAX_AGE_S = 7 * 24 * 60 * 60;

const enc = new TextEncoder();

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
  return Array.from(sig, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Constant-time string comparison (length is not secret here: both sides are hex digests or the password). */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(secret: string, now = Date.now()): Promise<string> {
  const exp = Math.floor(now / 1000) + SESSION_MAX_AGE_S;
  return `${exp}.${await hmac(secret, `pareeksha-web:${exp}`)}`;
}

export async function verifySessionToken(secret: string, token: string | undefined, now = Date.now()): Promise<boolean> {
  if (!token) return false;
  const dot = token.indexOf(".");
  if (dot < 1) return false;
  const exp = Number(token.slice(0, dot));
  if (!Number.isInteger(exp) || exp * 1000 < now) return false;
  return safeEqual(token.slice(dot + 1), await hmac(secret, `pareeksha-web:${exp}`));
}

/** Only same-site paths are allowed as a post-login destination. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\") || next.startsWith("/login")) return "/";
  return next;
}
