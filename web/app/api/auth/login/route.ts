import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/session";
import { backend, origin, clearFailures, loginRedirect, noteFailure, signIn, throttled, toSessionUser } from "@/lib/auth-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** A wrong password waits before answering, which slows guessing from one client. */
const FAIL_DELAY_MS = 800;
const field = (f: FormData | null, k: string) => (typeof f?.get(k) === "string" ? (f!.get(k) as string) : "");

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null);
  const email = field(form, "email").trim().toLowerCase();
  const password = field(form, "password");
  const next = safeNext(field(form, "next"));
  if (!email || !password) return loginRedirect(req, { error: "empty", next });

  const key = `${req.headers.get("x-forwarded-for") ?? "local"}|${email}`;
  if (throttled(key)) return loginRedirect(req, { error: "locked", next });

  const r = await backend("/auth/login", { body: { email, password } });
  const user = r.status === 200 ? toSessionUser(r.data) : null;
  if (!user) {
    if (r.status === 401) noteFailure(key);
    await new Promise((res) => setTimeout(res, FAIL_DELAY_MS));
    return loginRedirect(req, { error: r.status === 401 ? "wrong" : r.status === 403 ? "disabled" : "down", next });
  }
  clearFailures(key);
  return signIn(req, user, next);
}

export function GET(req: NextRequest) {
  return NextResponse.redirect(new URL("/login", origin(req)), 303);
}
