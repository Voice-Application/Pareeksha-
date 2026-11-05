import type { NextRequest } from "next/server";
import { backend, loginRedirect, signIn, toSessionUser } from "@/lib/auth-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const field = (f: FormData | null, k: string) => (typeof f?.get(k) === "string" ? (f!.get(k) as string) : "");

/** Creates the first account, an admin. The backend refuses once any account exists. */
export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null);
  const name = field(form, "name").trim();
  const email = field(form, "email").trim().toLowerCase();
  const password = field(form, "password");
  if (!name || !email) return loginRedirect(req, { error: "empty" });
  if (password !== field(form, "confirm")) return loginRedirect(req, { error: "mismatch" });
  if (password.length < 10) return loginRedirect(req, { error: "short" });

  const r = await backend("/auth/bootstrap", { body: { name, email, password } });
  const user = r.status === 201 ? toSessionUser(r.data) : null;
  if (!user) return loginRedirect(req, { error: r.status === 409 ? "closed" : r.status === 422 ? "invalid" : "down" });
  return signIn(req, user, "/");
}
