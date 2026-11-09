import Link from "next/link";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import "./landing.css";
import { DemoRun } from "./demo-run";
import { DemoTabs } from "./demo-tabs";

const REPO = "https://github.com/voice-application/pareeksha-";

/** The three steps of a run, in the order the product performs them. */
const STEPS = [
  { n: "1", title: "Paste your prompt", body: "Drop in the system prompt that drives your voice or chat bot." },
  { n: "2", title: "We role-play callers", body: "Pareeksha runs normal and tricky callers against it, the way real people phone in." },
  { n: "3", title: "You see what broke", body: "Every rule the bot broke, scored and cited back to the exact line it came from." },
];

/**
 * What the platform does beyond the one-screen test. Each line is grounded in a real feature page
 * so the copy stays honest; the href deep-links into that tool.
 */
const FEATURES = [
  {
    title: "Synthetic callers & personas",
    body: "Build callers with their own language, code-mix, voice, mood and habits, and scenarios that say what the caller is trying to do.",
    href: "/personas",
  },
  {
    title: "Noisy phone lines",
    body: "Put a call on a real line: codec, band-limit, background noise, SNR and packet loss — not just a clean studio mic.",
    href: "/noise-profiles",
  },
  {
    title: "Dialect & accent gaps",
    body: "Measure how the speech recogniser performs per dialect and phone line, with sample sizes and 95% confidence intervals.",
    href: "/dialect",
  },
  {
    title: "RAG lab",
    body: "Compare chunking, embedding and retrieval setups against no-RAG and full-context baselines on the same scenarios.",
    href: "/rag-lab",
  },
  {
    title: "Regression & audits",
    body: "Promote a failed call into a test future runs must not fail, and score real recorded calls with the same rubric.",
    href: "/regression",
  },
  {
    title: "Integrations",
    body: "Receive recordings from your telephony with a signed webhook, and send evaluated calls on to your CRM.",
    href: "/integrations",
  },
];

/**
 * The marketing landing page for Pareeksha, rendered outside the app shell at /welcome.
 * Leads with the product's job in plain words and consumes the shared app design tokens,
 * so clicking into the dashboard is continuous rather than a visual cliff.
 */
export function Landing() {
  return (
    <div className="lp">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[400] focus:rounded-sm focus:bg-surface focus:p-2"
      >
        Skip to content
      </a>

      <header className="lp-nav">
        <div className="lp-container lp-nav__bar">
          <Link href="/welcome" className="lp-wordmark" aria-label="Pareeksha home">
            Pareeksha
          </Link>
          <nav aria-label="Product" className="lp-nav__links">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a className="lp-nav__repo" href={REPO}>
              Repository
            </a>
            <ThemeToggle />
            <Link className="lp-btn" href="/test">
              Test my prompt
            </Link>
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="lp-hero" aria-labelledby="hero-head">
          <div className="lp-container lp-hero__grid">
            <div className="lp-hero__text">
              <h1 id="hero-head">Find the bugs in your bot&rsquo;s prompt before your customers do.</h1>
              <p className="lp-lead">
                Paste a system prompt. Pareeksha role-plays normal and tricky callers, then shows you every rule the bot
                broke, with the exact line.
              </p>
              <div className="lp-hero__actions">
                <Link className="lp-btn" href="/test">
                  Test my prompt
                </Link>
                <a className="lp-link" href="#how">
                  See how it works
                </a>
              </div>
            </div>

            <figure className="lp-hero__fig">
              {/* A self-playing sample run (prompt -> conversation -> verdict), not a static shot. */}
              <DemoRun />
              <figcaption className="lp-caption">A sample run: the prompt, the call, and the rules it broke &mdash; scored against the pass line.</figcaption>
            </figure>
          </div>
        </section>

        <section id="how" className="lp-how" aria-labelledby="how-head">
          <div className="lp-container">
            <h2 id="how-head" className="lp-how__head">
              How it works
            </h2>
            <ol className="lp-steps">
              {STEPS.map((step) => (
                <li key={step.n} className="lp-step">
                  <span className="lp-step__n num" aria-hidden="true">
                    {step.n}
                  </span>
                  <h3 className="lp-step__title">{step.title}</h3>
                  <p className="lp-step__body">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="features" className="lp-features" aria-labelledby="features-head">
          <div className="lp-container">
            <h2 id="features-head" className="lp-features__head">
              More than one test
            </h2>
            <p className="lp-features__lead">
              The quick test is the front door. Underneath, Pareeksha is a full QA suite for voice and chat bots.
            </p>
            <ul className="lp-features__grid">
              {FEATURES.map((f) => (
                <li key={f.href} className="lp-feature">
                  <Link href={f.href} className="lp-feature__link">
                    <h3 className="lp-feature__title">{f.title}</h3>
                    <p className="lp-feature__body">{f.body}</p>
                  </Link>
                </li>
              ))}
            </ul>

            <div className="lp-showcase">
              <h3 className="lp-showcase__head">See the output</h3>
              <DemoTabs />
            </div>
          </div>
        </section>

        <section className="lp-cta" aria-labelledby="cta-head">
          <div className="lp-container lp-cta__row">
            <div className="lp-cta__text">
              <h2 id="cta-head">See what your prompt misses.</h2>
              <p className="lp-lead">Paste it once and read the first failing call with the line it broke.</p>
            </div>
            <Link className="lp-btn" href="/test">
              Test my prompt
            </Link>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <div className="lp-container lp-foot__row">
          <ul className="lp-foot__links">
            <li>
              <Link href="/test">Test a prompt</Link>
            </li>
            <li>
              <Link href="/runs">Runs</Link>
            </li>
            <li>
              <Link href="/agents">Agents</Link>
            </li>
            <li>
              <a href={REPO}>Repository</a>
            </li>
          </ul>
          <p className="lp-foot__line">Fixtures are synthetic. Voice and dialect clips need consent.</p>
        </div>
      </footer>
    </div>
  );
}
