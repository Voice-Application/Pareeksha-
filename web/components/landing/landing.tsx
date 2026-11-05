import Image from "next/image";
import Link from "next/link";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import "./landing.css";
import verdictShot from "./shots/call-verdict.png";
import transcriptShot from "./shots/call-transcript-light.png";
import { RunReplay } from "./run-replay";
import { CallPlayer } from "./call-player";

const REPO = "https://github.com/voice-application/pareeksha-";

/** Lines from the seed (pareeksha.seed), loudest first. */
const LINES = ["auto_rickshaw_0db", "pstn_market_5db", "mobile_bus_5db", "pstn_street_10db", "mobile_weak_signal"];

/** Caller personas from the seed, with the language each one speaks. */
const PEOPLE = [
  { name: "Manju, auto driver", lang: "Kannada" },
  { name: "Sunita, worried borrower", lang: "Hindi" },
  { name: "Lakshmamma, elderly", lang: "Kannada" },
  { name: "Neha, switcher", lang: "English" },
  { name: "The Interrupter", lang: "Kannada" },
];

export function Landing() {
  return (
    <div data-theme="cobalt" className="lp">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[400] focus:rounded-sm focus:p-2">Skip to content</a>
      <header className="lp-nav">
        <div className="container">
          <Link href="/welcome" className="lp-wordmark" aria-label="Pareeksha home">Pareeksha</Link>
          <nav aria-label="Product" className="lp-nav__links">
            <a href="#questions">How it works</a>
            <a className="lp-nav__repo" href={REPO}>Repository</a>
            <ThemeToggle />
            <Link className="btn" href="/">Open the dashboard</Link>
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="lp-hero" aria-labelledby="hero-head">
          <div className="container">
            <div className="lp-hero__text">
              <h1 id="hero-head">Call your voice bot before customers do.</h1>
              <p className="lead">Synthetic Indian callers on noisy phone lines, every call scored with evidence.</p>
              <div className="lp-hero__actions">
                <Link className="btn" href="/runs/new">Start a run</Link>
                <a className="btn btn--quiet" href="#questions">Hear a failed call</a>
              </div>
            </div>
            <figure className="lp-fig">
              <RunReplay />
              <figcaption className="lp-caption">A recorded run against the bundled mock bot, which has planted bugs.</figcaption>
            </figure>
          </div>
        </section>

        <section id="questions" className="lp-q" aria-labelledby="q-why">
          <div className="container">
            <div className="lp-q__head">
              <h2 id="q-why">Why did this call fail?</h2>
              <p className="lead">A real call from that run. Pick a code to hear the turns it cites.</p>
            </div>
            <CallPlayer />
          </div>
        </section>
        <section className="lp-q" aria-labelledby="q-who">
          <div className="container">
            <div className="lp-q__head">
              <h2 id="q-who">Which callers, on which lines?</h2>
              <p className="lead">Kannada, Hindi and English callers, mixing languages the way people do.</p>
            </div>
            <div className="lp-split lp-split--top">
              <div className="lp-index">
                <div>
                  <p className="lp-people__title">Some of the callers</p>
                  <ul className="lp-people">
                    {PEOPLE.map((p) => (
                      <li key={p.name}><span>{p.name}</span><span>{p.lang}</span></li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="lp-people__title">Phone lines, all 8 kHz A-law</p>
                  <ul className="lp-lines">
                    {LINES.map((l) => <li key={l}>{l}</li>)}
                  </ul>
                </div>
              </div>
              <figure className="lp-fig">
                <div className="lp-panel lp-panel--transcript" data-slot="call-transcript" data-kind="product" data-alt="The transcript of the failed call in Kannada, with what the agent's speech recognition heard and the failure codes on each turn">
                  <Image src={transcriptShot} alt="Transcript in Kannada: the caller asks for a human agent in Kannada and English; the agent's speech recognition mishears it, and the agent's turns carry missing_disclosure and language_mismatch." sizes="(min-width: 60rem) 680px, 100vw" />
                </div>
                <figcaption className="lp-caption">Kiran asks for a human in Kanglish. The agent hears it wrong.</figcaption>
              </figure>
            </div>
          </div>
        </section>

        <section className="lp-q lp-q--gap" aria-labelledby="q-judge">
          <div className="container lp-judge">
            <div className="lp-statement-row">
              <h2 id="q-judge" className="lp-statement">Treat a score as a signal, then read the evidence.</h2>
              <div className="lp-statement-row__aside">
                <p>The judge is an LLM, not ground truth. Check it against your own labels.</p>
                <p><Link className="link" href="/calibration">Open calibration</Link></p>
              </div>
            </div>
            <figure className="lp-fig lp-fig--verdict">
              <div className="lp-panel lp-panel--verdict" data-slot="call-verdict" data-kind="product" data-alt="The verdict panel of one call: critical failure, needs human review, the score against the pass line, the failure codes and the override button">
                <Image src={verdictShot} alt="Verdict for one call: critical failure, needs human review, overall score 13.75 of 100 against a pass line of 80, and an Override judge score button." sizes="(min-width: 60rem) 408px, 100vw" />
              </div>
              <figcaption className="lp-caption">A person can override any verdict from the call page.</figcaption>
            </figure>
          </div>
        </section>

        <section className="lp-q lp-final" aria-labelledby="q-final">
          <div className="container">
            <div className="lp-split__text">
              <h2 id="q-final">Hear your bot fail before a customer does.</h2>
              <p className="lead">Pick an agent, a caller and a phone line. The run scores every call with the turns it cites.</p>
            </div>
            <div className="lp-hero__actions">
              <Link className="btn" href="/runs/new">Start a run</Link>
              <Link className="btn btn--quiet" href="/agents">Choose an agent</Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <div className="container">
          <p className="lp-foot__mast" aria-hidden="true">Pareeksha</p>
          <div className="lp-foot__row">
            <ul className="lp-foot__links">
              <li><Link href="/runs">Runs</Link></li>
              <li><Link href="/agents">Agents</Link></li>
              <li><a href={`${REPO}/tree/main/docs/guides`}>Guides</a></li>
              <li><a href={REPO}>Repository</a></li>
            </ul>
            <Link className="btn" href="/runs/new">Start a run</Link>
          </div>
          <p className="lp-foot__line">Fixtures are synthetic. Voice and dialect clips need consent.</p>
        </div>
      </footer>
    </div>
  );
}
