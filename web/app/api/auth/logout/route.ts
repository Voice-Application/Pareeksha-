import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, SIGNED_IN_COOKIE } from "@/lib/session";
import { origin } from "@/lib/auth-server";

export const dynamic = "force-dynamic";

/** Clears both cookies and returns to the login page. POST only, so a link or image cannot sign someone out. */
export async function POST(req: NextRequest) {
  const res = NextResponse.redirect(new URL("/login?signed_out=1", origin(req)), 303);
  res.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0, httpOnly: true, sameSite: "lax" });
  res.cookies.set(SIGNED_IN_COOKIE, "", { path: "/", maxAge: 0, sameSite: "lax" });
  return res;
}
