import Image from "next/image";
import Link from "next/link";
import "./landing.css";
import audioShot from "./shots/call-audio.png";
import verdictShot from "./shots/call-verdict.png";
import transcriptShot from "./shots/call-transcript-light.png";
import { RunReplay } from "./run-replay";
import { PipelineLive } from "./pipeline-live";
import { CopySteps } from "./copy-steps";

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

const TAGS = [
  { tag: "missing_disclosure", line: "The required disclosure never came." },
  { tag: "language_mismatch", line: "Answered in a language the caller did not use." },
  { tag: "wrong_fact", line: "Confirmed a fact that is wrong." },
];

const QUICK_START = [
  "docker compose --profile workers up -d --build",
  "docker compose run --rm api python -m pareeksha.seed",
  "pip install ./sdk/python",
  "set -a; . ./.env; set +a",
  'pareeksha login --url http://localhost:8000 --key "$PAREEKSHA_API_KEY"',
  'pareeksha run --agent "EMI Reminder Bot" --tags promise_to_pay --persona "Manju — auto driver" --noise clean_16k --wait',
];

export function Landing() {
  return (
    <div className="lp" data-theme="dusk">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[400] focus:rounded-sm focus:p-2">Skip to content</a>
      <header className="lp-nav">
        <div className="container">
          <Link href="/welcome" className="lp-wordmark" aria-label="Pareeksha home">Pareeksha</Link>
          <nav aria-label="Product" className="lp-nav__links">
            <a href="#questions">How it works</a>
            <a className="lp-nav__repo" href={REPO}>Repository</a>
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
                <a className="btn btn--quiet" href="#quick-start">Run it locally</a>
              </div>
            </div>
            <figure className="lp-fig">
              <RunReplay />
              <figcaption className="lp-caption">A recorded run against the bundled mock bot, which has planted bugs, replayed in the order it finished.</figcaption>
            </figure>
          </div>
        </section>

        <section id="questions" className="lp-q" aria-labelledby="q-why">
          <div className="container lp-split lp-split--flip">
            <div className="lp-split__text">
              <h2 id="q-why">Why did this call fail?</h2>
              <p className="lead">The judge cites the turn, and the audio jumps there.</p>
              <dl className="lp-tags">
                {TAGS.map((t) => (
                  <div key={t.tag}><dt>{t.tag}</dt><dd>{t.line}</dd></div>
                ))}
              </dl>
            </div>
            <figure className="lp-fig">
              <div className="lp-scroll" tabIndex={0} role="region" aria-label="Call audio timeline, scrolls sideways on small screens">
                <div className="lp-panel lp-panel--audio" data-slot="call-audio" data-kind="product" data-alt="The audio timeline of one failed call: agent and caller lanes, silences, a tool call and response latency">
                  <Image src={audioShot} alt="Audio timeline of a 36 second call: agent and caller waveforms, two long silences, a tool call, and response latencies of 1.0 and 1.3 seconds." sizes="(min-width: 60rem) 680px, 600px" />
                </div>
              </div>
              <figcaption className="lp-caption">One failed call from the same run.</figcaption>
            </figure>
          </div>
        </section>

        <section className="lp-q" aria-labelledby="q-flow">
          <div className="container">
            <div className="lp-q__head">
              <h2 id="q-flow">What happens on one call?</h2>
              <p className="lead">Each step is a Kafka worker. Click one to stop on it.</p>
            </div>
            <PipelineLive />
          </div>
        </section>

        <section className="lp-q lp-bone" aria-labelledby="q-who">
          <div className="container">
            <div className="lp-q__head">
              <h2 id="q-who">Which callers, on which lines?</h2>
              <p className="lead">Kannada, Hindi and English callers, mixing languages the way people do.</p>
            </div>
            <div className="lp-split lp-split--bone">
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

        <section className="lp-q" aria-labelledby="q-ci">
          <div className="container lp-split">
            <div className="lp-split__text">
              <h2 id="q-ci">Can it fail a pull request?</h2>
              <p className="lead">Yes. The GitHub Action runs a suite and fails the check on any of these.</p>
              <ul className="lp-exits">
                <li><span className="num">1</span><span>Pass rate under the threshold</span></li>
                <li><span className="num">2</span><span>A critical failure on any call</span></li>
                <li><span className="num">3</span><span>A regression on a promoted call</span></li>
              </ul>
            </div>
            <div className="lp-code"><span className="lp-code__name">.github/workflows/voice.yml</span><pre aria-label="GitHub workflow step"><code><span className="k">- uses:</span> voice-application/pareeksha-/action@main{"\n"}  <span className="k">with:</span>{"\n"}    <span className="k">api-url:</span> ${"{{"} secrets.PAREEKSHA_URL {"}}"}{"\n"}    <span className="k">api-key:</span> ${"{{"} secrets.PAREEKSHA_KEY {"}}"}{"\n"}    <span className="k">suite:</span> pr_check{"\n"}    <span className="c"># fail-under: &quot;80&quot;</span>{"\n"}    <span className="k">regression:</span> &quot;true&quot;</code></pre></div>
          </div>
        </section>

        <section className="lp-q lp-q--gap" aria-labelledby="q-judge">
          <div className="container lp-judge">
            <div className="lp-statement-row">
              <h2 id="q-judge" className="lp-statement">Treat a score as a signal, then read the evidence.</h2>
              <div className="lp-statement-row__aside">
                <p>The judge is an LLM, calibrated against labelled calls, not ground truth. Check it against your own labels.</p>
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

        <section id="quick-start" className="lp-q lp-close" aria-labelledby="q-start">
          <div className="container lp-split">
            <div className="lp-split__text">
              <h2 id="q-start">Can I run it on my own machine?</h2>
              <p className="lead">Yes, in Docker. You need Python 3.11, a Gnani key and a DeepSeek key.</p>
              <div className="lp-hero__actions">
                <a className="btn btn--quiet" href={`${REPO}/blob/main/docs/guides/01-quickstart.md`}>Read the quick start</a>
              </div>
            </div>
            <div className="lp-code lp-code--steps">
              <CopySteps steps={QUICK_START} />
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
