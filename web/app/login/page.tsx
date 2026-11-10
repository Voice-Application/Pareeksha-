import type { Metadata } from "next";
import Link from "next/link";
import { CircleAlert, FileSearch, Languages, ListChecks } from "lucide-react";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { safeNext } from "@/lib/session";
import { backend } from "@/lib/auth-server";
// The live landing demo replaces a static screenshot that drifted from the current design.
import "@/components/landing/landing.css";
import { DemoRun } from "@/components/landing/demo-run";

/** What the dashboard does, in the product's own terms; shown beside the sign-in form. */
const FEATURES = [
  { icon: ListChecks, title: "Every rule in your prompt, checked", body: "Pareeksha finds the rules in a system prompt and shows which ones the bot kept or broke." },
  { icon: FileSearch, title: "The exact line it slipped on", body: "Each broken rule comes with the bot's own words and the conversation it happened in." },
  { icon: Languages, title: "Callers in Kannada and Hindi", body: "Test callers speak your customers' languages, not just English." },
];

export const metadata: Metadata = { title: "Sign in to Pareeksha", description: "Sign in to the Pareeksha dashboard." };
export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  wrong: "That email and password do not match.",
  empty: "Fill in every field to continue.",
  locked: "Too many failed attempts. Try again in ten minutes.",
  disabled: "This account is disabled. Ask an admin to turn it back on.",
  down: "The API did not answer. Check that it is running, then try again.",
  config: "SESSION_SECRET is not set on the server (16 characters or more, not the published default).",
  mismatch: "The two passwords are not the same.",
  short: "Use at least 10 characters for the password.",
  invalid: "Check the email address and password length (10 to 200 characters).",
  closed: "An admin already exists. Sign in instead.",
};

const input = "h-12 w-full rounded-sm border border-border-strong bg-surface px-3 text-base text-fg transition-[border-color] duration-150 hover:border-fg aria-[invalid=true]:border-fail";
const submit = "inline-flex h-12 items-center justify-center rounded-pill bg-accent px-6 text-base font-medium text-accent-on transition-[background-color,transform] duration-150 hover:bg-accent-hi active:translate-y-px motion-reduce:transition-none";

/** A labelled required input for the login form, with an optional hint and invalid state. */
function Field({ id, label, type = "text", autoComplete, autoFocus, invalid, hint }: { id: string; label: string; type?: string; autoComplete?: string; autoFocus?: boolean; invalid?: boolean; hint?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <input id={id} name={id} type={type} autoComplete={autoComplete} autoFocus={autoFocus} required aria-invalid={invalid ? true : undefined} className={input} />
      {hint && <p className="text-sm text-subtle">{hint}</p>}
    </div>
  );
}

/** Sign-in page: shows first-user setup, sign-in or an unavailable notice depending on the backend auth status. */
export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  /** The single string value of a search param; arrays and missing keys read as undefined. */
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : undefined);
  const next = safeNext(one("next"));
  const error = ERRORS[one("error") ?? ""];
  const open = process.env.AUTH_DISABLED === "1";
  const status = open ? null : await backend("/auth/status");
  const hasUsers = (status?.data as { has_users?: boolean } | null)?.has_users;
  const setup = !open && status?.status === 200 && hasUsers === false;
  const unavailable = !open && status?.status !== 200;

  return (
    <div className="min-h-dvh bg-canvas text-fg">
      <div className="mx-auto grid min-h-dvh w-full max-w-[1180px] items-center gap-10 px-6 py-10 min-[961px]:grid-cols-2 min-[961px]:gap-16 min-[961px]:px-12">
        <main id="main" className="mx-auto flex w-full max-w-[25rem] flex-col gap-8 min-[961px]:mx-0 min-[961px]:ml-auto">
          <div className="flex items-center justify-between"><Link href="/welcome" className="display w-fit text-lg">Pareeksha</Link><ThemeToggle /></div>
          <div className="flex flex-col gap-3">
            <h1 className="display text-xl">{setup ? "Create the admin account" : "Sign in to the dashboard"}</h1>
            <p className="text-muted">
              {open
                ? "Sign-in is turned off on this instance (AUTH_DISABLED), so the dashboard is open."
                : setup
                  ? "No one has an account yet. The first account is the admin, who adds everyone else from Users."
                  : "Use the email and password an admin created for you."}
            </p>
          </div>

          {one("signed_out") && !error && <p role="status" className="rounded-sm bg-pass-tint px-4 py-3 text-sm text-pass-fg">You are signed out.</p>}
          {error && (
            <p role="alert" className="flex items-start gap-1.5 text-sm text-fail-fg">
              <CircleAlert size={16} strokeWidth={1.6} className="mt-0.5 shrink-0" aria-hidden />
              {error}
            </p>
          )}

          {open ? (
            <Link href={next} className={`${submit} w-fit`}>Open the dashboard</Link>
          ) : unavailable ? (
            <p role="alert" className="flex items-start gap-1.5 text-sm text-fail-fg">
              <CircleAlert size={16} strokeWidth={1.6} className="mt-0.5 shrink-0" aria-hidden />
              {ERRORS.down}
            </p>
          ) : setup ? (
            <form method="post" action="/api/auth/setup" className="flex flex-col gap-5">
              <Field id="name" label="Name" autoComplete="name" autoFocus />
              <Field id="email" label="Email" type="email" autoComplete="email" />
              <Field id="password" label="Password" type="password" autoComplete="new-password" hint="10 characters or more." />
              <Field id="confirm" label="Repeat the password" type="password" autoComplete="new-password" />
              <button type="submit" className={submit}>Create admin account</button>
            </form>
          ) : (
            <form method="post" action="/api/auth/login" className="flex flex-col gap-5">
              <input type="hidden" name="next" value={next} />
              <Field id="email" label="Email" type="email" autoComplete="username" autoFocus invalid={!!error} />
              <Field id="password" label="Password" type="password" autoComplete="current-password" invalid={!!error} />
              <button type="submit" className={submit}>Sign in</button>
              <p className="text-sm text-subtle">There is no public sign-up. An admin adds accounts from Users.</p>
            </form>
          )}

          <p className="text-sm text-subtle">
            New here? <Link href="/welcome" className="text-accent-fg underline underline-offset-2">See what Pareeksha does</Link>
          </p>
        </main>

        <aside aria-label="What Pareeksha does" className="hidden w-full max-w-[30rem] flex-col gap-6 min-[961px]:flex">
          {/* The same self-playing sample run as the landing page: the real component, so it always matches the app. */}
          <figure className="m-0 flex flex-col gap-3">
            <DemoRun />
            <figcaption className="text-sm text-subtle">Sample data. A prompt, a call, and the rule the bot broke, scored against the pass line.</figcaption>
          </figure>
          <ul className="flex flex-col gap-4">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex gap-3">
                <span className="grid size-8 shrink-0 place-items-center rounded-sm bg-accent-tint text-accent-fg" aria-hidden>
                  <Icon size={16} strokeWidth={1.6} />
                </span>
                <div className="min-w-0">
                  <p className="font-medium">{title}</p>
                  <p className="text-sm text-muted">{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
