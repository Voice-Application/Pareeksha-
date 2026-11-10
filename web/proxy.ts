import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, sessionSecret, verifySessionToken } from "@/lib/session";

/**
 * Account gate. Every page and API call needs a valid signed session (set by /login or its first-admin
 * setup); signed-out page requests go to /login, signed-out API requests get 401. The landing page, the
 * login page and the auth endpoints are open. AUTH_DISABLED=1 turns the gate off for local development and
 * the browser tests only. Next.js 16 renamed the `middleware` file convention to `proxy`.
 */
const OPEN_PATHS = ["/login", "/welcome", "/api/auth/login", "/api/auth/setup", "/api/auth/logout"];

export async function proxy(req: NextRequest) {
  if (process.env.AUTH_DISABLED === "1") return NextResponse.next();

  const { pathname, search } = req.nextUrl;
  if (OPEN_PATHS.includes(pathname)) return NextResponse.next();

  const secret = sessionSecret();
  if (!secret) return new NextResponse("SESSION_SECRET is not set (16 characters or more, not the published default). Sign-in is unavailable.", { status: 503 });

  const user = await verifySessionToken(secret, req.cookies.get(SESSION_COOKIE)?.value);
  if (user) {
    // Every API route behind these pages needs the admin scope.
    if ((pathname.startsWith("/settings/users") || pathname.startsWith("/settings/api-keys")) && user.role !== "admin") return NextResponse.redirect(new URL("/", req.url), 303);
    return NextResponse.next();
  }

  if (pathname.startsWith("/api/")) return new NextResponse("Authentication required", { status: 401 });
  const login = new URL("/login", req.url);
  login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login, 303);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|landing/).*)"],
};
