import Image from "next/image";
import Link from "next/link";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import "./landing.css";
import verdictLight from "./shots/verdict-light.png";
import verdictDark from "./shots/verdict-dark.png";

const REPO = "https://github.com/voice-application/pareeksha-";

/** The three steps of a run, in the order the product performs them. */
const STEPS = [
  { n: "1", title: "Paste your prompt", body: "Drop in the system prompt that drives your voice or chat bot." },
  { n: "2", title: "We role-play callers", body: "Pareeksha runs normal and tricky callers against it, the way real people phone in." },
  { n: "3", title: "You see what broke", body: "Every rule the bot broke, scored and cited back to the exact line it came from." },
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
              {/* Theme-matched product shot: a light screenshot in light mode, a dark one in dark mode,
                  so the image never sits as a dark block on a light page (or vice versa). */}
              <div className="lp-panel">
                <Image
                  className="lp-shot lp-shot--light"
                  src={verdictLight}
                  alt="A scored verdict for one call: critical failure, an overall score of 57.5 out of 100 against a pass line of 80, and a button to override the judge's score."
                  sizes="(min-width: 60rem) 420px, 100vw"
                  placeholder="blur"
                />
                <Image
                  className="lp-shot lp-shot--dark"
                  src={verdictDark}
                  alt="A scored verdict for one call: critical failure, an overall score of 57.5 out of 100 against a pass line of 80, and a button to override the judge's score."
                  sizes="(min-width: 60rem) 420px, 100vw"
                  placeholder="blur"
                />
              </div>
              <figcaption className="lp-caption">One call&rsquo;s verdict: the score against the pass line, and the rules it broke.</figcaption>
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
