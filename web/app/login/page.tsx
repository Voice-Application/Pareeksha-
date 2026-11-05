import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { CircleAlert, LockKeyhole } from "lucide-react";
import { safeNext } from "@/lib/session";
import verdictShot from "@/components/landing/shots/call-verdict.png";

export const metadata: Metadata = { title: "Sign in to Pareeksha", description: "Sign in to the Pareeksha dashboard." };
export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  wrong: "That password is not right. Check it against WEB_PASSWORD in the server's .env.",
  empty: "Enter the password to continue.",
};

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : undefined);
  const next = safeNext(one("next"));
  const error = ERRORS[one("error") ?? ""];
  const gated = !!process.env.WEB_PASSWORD;

  return (
    <div className="min-h-dvh bg-canvas text-fg">
      <div className="mx-auto grid min-h-dvh w-full max-w-[1360px] items-center gap-12 px-6 py-10 min-[961px]:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] min-[961px]:px-16">
        <main id="main" className="flex w-full max-w-[26rem] flex-col gap-8">
          <Link href="/welcome" className="display w-fit text-lg">Pareeksha</Link>
          <div className="flex flex-col gap-3">
            <h1 className="display text-xl">Sign in to the dashboard</h1>
            <p className="text-muted">
              {gated ? "This instance is protected by the password set as WEB_PASSWORD on the server." : "This instance has no password set, so the dashboard is open."}
            </p>
          </div>

          {one("signed_out") && !error && <p role="status" className="rounded-sm bg-pass-tint px-4 py-3 text-sm text-pass-fg">You are signed out.</p>}

          {gated ? (
            <form method="post" action="/api/auth/login" className="flex flex-col gap-5">
              <input type="hidden" name="next" value={next} />
              <div className="flex flex-col gap-1.5">
                <label htmlFor="password" className="text-sm font-medium">Password</label>
                <div className="relative">
                  <LockKeyhole size={16} strokeWidth={1.6} className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-subtle" aria-hidden />
                  <input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    autoFocus
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? "password-error" : "password-help"}
                    className="h-12 w-full rounded-sm border border-border-strong bg-surface pr-3 pl-10 text-base text-fg transition-[border-color] duration-150 hover:border-fg aria-[invalid=true]:border-fail"
                  />
                </div>
                {error ? (
                  <p id="password-error" role="alert" className="flex items-start gap-1.5 text-sm text-fail-fg">
                    <CircleAlert size={16} strokeWidth={1.6} className="mt-0.5 shrink-0" aria-hidden />
                    {error}
                  </p>
                ) : (
                  <p id="password-help" className="min-h-5 text-sm text-subtle">Any username works for scripts that use HTTP Basic auth.</p>
                )}
              </div>
              <button type="submit" className="inline-flex h-12 items-center justify-center rounded-pill bg-accent px-6 text-base font-medium text-accent-on transition-[background-color,transform] duration-150 hover:bg-accent-hi active:translate-y-px motion-reduce:transition-none">
                Sign in
              </button>
            </form>
          ) : (
            <Link href={next} className="inline-flex h-12 w-fit items-center rounded-pill bg-accent px-6 text-base font-medium text-accent-on hover:bg-accent-hi">
              Open the dashboard
            </Link>
          )}

          <p className="text-sm text-subtle">
            New here? <Link href="/welcome" className="text-accent-fg underline underline-offset-2">See what Pareeksha does</Link>
          </p>
        </main>

        <figure className="hidden min-[961px]:block">
          <div className="grid place-items-center rounded-lg bg-sunken p-12">
            <div className="w-full max-w-[408px] overflow-hidden rounded-lg" style={{ boxShadow: "var(--shadow-float)" }}>
              <Image src={verdictShot} alt="A call's verdict: critical failure, needs human review, overall score 13.75 of 100 against a pass line of 80." sizes="408px" priority />
            </div>
          </div>
          <figcaption className="mt-3 text-sm text-subtle">A call from the planted-bugs run, as the dashboard shows it.</figcaption>
        </figure>
      </div>
    </div>
  );
}
