import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/session";
import { backend, origin, loginRedirect, refuseCrossSite, signIn, toSessionUser } from "@/lib/auth-server";
import { clearLoginFailures, clientAddress, loginLocked, noteLoginFailure } from "@/lib/login-throttle";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** A wrong password waits before answering, which slows guessing from one client. */
const FAIL_DELAY_MS = 800;
const field = (f: FormData | null, k: string) => (typeof f?.get(k) === "string" ? (f!.get(k) as string) : "");

export async function POST(req: NextRequest) {
  const refused = refuseCrossSite(req);
  if (refused) return refused;
  const form = await req.formData().catch(() => null);
  const email = field(form, "email").trim().toLowerCase();
  const password = field(form, "password");
  const next = safeNext(field(form, "next"));
  if (!email || !password) return loginRedirect(req, { error: "empty", next });

  const client = clientAddress(req.headers);
  if (loginLocked(email, client)) return loginRedirect(req, { error: "locked", next });

  const r = await backend("/auth/login", { body: { email, password } });
  const user = r.status === 200 ? toSessionUser(r.data) : null;
  if (!user) {
    if (r.status === 401) noteLoginFailure(email, client);
    await new Promise((res) => setTimeout(res, FAIL_DELAY_MS));
    return loginRedirect(req, { error: r.status === 401 ? "wrong" : r.status === 403 ? "disabled" : "down", next });
  }
  clearLoginFailures(email);
  return signIn(req, user, next);
}

export function GET(req: NextRequest) {
  return NextResponse.redirect(new URL("/login", origin(req)), 303);
}
