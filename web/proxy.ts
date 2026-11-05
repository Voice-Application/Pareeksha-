import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, safeEqual, verifySessionToken } from "@/lib/session";

/**
 * Optional WEB_PASSWORD gate (TRD 11). Next.js 16 renamed the `middleware` file convention to `proxy`.
 * When WEB_PASSWORD is unset the gate is off. When set, a request passes with either a valid session
 * cookie (set by the /login form) or HTTP Basic auth with that password (any username), so scripts and
 * the CLI keep working. Signed-out page requests go to /login; signed-out API requests get 401.
 */
const OPEN_PATHS = ["/login", "/api/auth/login", "/api/auth/logout"];

function basicOk(req: NextRequest, password: string): boolean {
  const header = req.headers.get("authorization") ?? "";
  if (!header.startsWith("Basic ")) return false;
  try {
    const decoded = atob(header.slice(6));
    return safeEqual(decoded.slice(decoded.indexOf(":") + 1), password);
  } catch {
    return false;
  }
}

export async function proxy(req: NextRequest) {
  const password = process.env.WEB_PASSWORD;
  if (!password) return NextResponse.next();

  const { pathname, search } = req.nextUrl;
  if (OPEN_PATHS.includes(pathname)) return NextResponse.next();
  if (basicOk(req, password)) return NextResponse.next();
  if (await verifySessionToken(password, req.cookies.get(SESSION_COOKIE)?.value)) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return new NextResponse("Authentication required", {
      status: 401,
      headers: { "www-authenticate": 'Basic realm="Pareeksha", charset="UTF-8"' },
    });
  }
  const login = new URL("/login", req.url);
  login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login, 303);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|fonts/).*)"],
};
