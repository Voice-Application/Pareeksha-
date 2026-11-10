import Link from "next/link";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import "./landing.css";
import { DemoRun } from "./demo-run";
import { DemoTabs } from "./demo-tabs";
import { DEMO_CALLER_LINE, DEMO_CATCHES } from "./demo-data";

const REPO = "https://github.com/voice-application/pareeksha-";

/** The three steps of a run, in the order the product performs them. */
const STEPS = [
  { n: "1", title: "Paste your prompt", body: "The system prompt behind your voice or chat bot." },
  { n: "2", title: "We role-play callers", body: "Normal and tricky ones, including Hindi and Kannada speakers." },
  { n: "3", title: "You see what broke", body: "Each broken rule, scored, with the line it came from." },
];

/** The rest of the suite, one link each into the tool (replaces the old icon card grid). */
const SUITE: { label: string; href: string }[] = [
  { label: "Personas", href: "/personas" },
  { label: "Noisy phone lines", href: "/noise-profiles" },
  { label: "Dialect gaps", href: "/dialect" },
  { label: "RAG lab", href: "/rag-lab" },
  { label: "Regression", href: "/regression" },
  { label: "Integrations", href: "/integrations" },
];

/** One line of sample speech, tagged with its language, with an English gloss under any Hindi line. */
function SampleLine({ text, lang, gloss }: { text: string; lang: "en" | "hi"; gloss?: string }) {
  return (
    <>
      <span lang={lang}>{text}</span>
      {gloss && <span className="lp-catch__gloss">{gloss}</span>}
    </>
  );
}

/**
 * The marketing landing page for Pareeksha, rendered outside the app shell at /welcome.
 * Leads with the product's job in plain words and consumes the shared app design tokens,
 * so clicking into the dashboard is continuous rather than a visual cliff. The middle of the
 * page shows real output from the seeded demo (demo-data.ts) instead of a feature grid.
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
            <a href="#features">What it catches</a>
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
              {/* The dialect story in one concrete line: a test caller speaking Kannada in its own script. */}
              <p className="lp-hero__caller">
                <span className="lp-hero__caller-who">Test caller, in {DEMO_CALLER_LINE.language}</span>
                <span className="lp-hero__caller-text" lang={DEMO_CALLER_LINE.lang}>
                  {DEMO_CALLER_LINE.text}
                </span>
                <span className="lp-hero__caller-gloss">
                  &ldquo;{DEMO_CALLER_LINE.gloss}&rdquo; Test callers can speak Kannada or Hindi, not just English.
                </span>
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
              <figcaption className="lp-caption">
                Sample data. The prompt, the call, and the rule it broke, scored against the pass line.
              </figcaption>
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
              What it catches
            </h2>
            <p className="lp-features__lead">
              Wrong answers from a sample bank bot, each beside the prompt rule it broke and the document line that says
              otherwise. Sample data.
            </p>
            <ol className="lp-catches">
              {DEMO_CATCHES.map((c) => (
                <li key={c.question} className="lp-catch">
                  <p className="lp-catch__rule">
                    <span className="lp-catch__k">Prompt rule</span>
                    <q>{c.rule}</q>
                  </p>
                  <dl className="lp-catch__lines">
                    <div className="lp-catch__row">
                      <dt>Caller asked</dt>
                      <dd>
                        <SampleLine text={c.question} lang={c.questionLang} gloss={c.gloss?.question} />
                      </dd>
                    </div>
                    <div className="lp-catch__row lp-catch__row--said">
                      <dt>Bot said</dt>
                      <dd>
                        <SampleLine text={c.said} lang={c.saidLang} gloss={c.gloss?.said} />
                      </dd>
                    </div>
                    <div className="lp-catch__row">
                      <dt>
                        Document <span className="mono">{c.doc}</span>
                      </dt>
                      <dd>
                        <SampleLine text={c.quote} lang={c.quoteLang} gloss={c.gloss?.quote} />
                      </dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ol>

            <div className="lp-showcase">
              <h3 className="lp-showcase__head">See the full output</h3>
              <DemoTabs />
            </div>

            <p className="lp-suite">
              <span className="lp-suite__k">Also in the suite</span>
              {SUITE.map((item) => (
                <Link key={item.href} href={item.href} className="lp-link">
                  {item.label}
                </Link>
              ))}
            </p>
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
              <Link href="/runs">Runs</Link>
            </li>
            <li>
              <Link href="/agents">Voice agents</Link>
            </li>
            <li>
              <a href={REPO}>Repository</a>
            </li>
          </ul>
          <p className="lp-foot__line">
            Every call on this page is sample data, not a real customer. Real voice and dialect recordings need the
            speaker&rsquo;s consent.
          </p>
        </div>
      </footer>
    </div>
  );
}
