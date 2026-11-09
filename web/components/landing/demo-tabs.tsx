"use client";

import { useId, useRef, useState } from "react";
import { DEMO_DIALECT, DEMO_DIMENSIONS, DEMO_RAG, DEMO_TURNS } from "./demo-data";

/**
 * An interactive showcase of what the platform produces, on baked sample data (no backend). Three
 * tabs: the judged transcript (click a turn to see the rule it broke and the per-dimension scores),
 * the dialect gap (ASR word-error-rate per dialect/line), and the RAG compare (retrieval setups).
 */

type TabKey = "transcript" | "dialect" | "rag";
const TABS: { key: TabKey; label: string }[] = [
  { key: "transcript", label: "Judged transcript" },
  { key: "dialect", label: "Dialect gaps" },
  { key: "rag", label: "RAG compare" },
];

/** The landing's sample-output tabs; keyboard follows the WAI-ARIA tabs pattern. */
export function DemoTabs() {
  const [tab, setTab] = useState<TabKey>("transcript");
  const base = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div className="lp-tabs">
      <div className="lp-tabs__list" role="tablist" aria-label="Sample output">
        {TABS.map((t, index) => (
          <button
            key={t.key}
            type="button"
            ref={(node) => { tabRefs.current[index] = node; }}
            role="tab"
            id={`${base}-tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls={`${base}-panel-${t.key}`}
            tabIndex={tab === t.key ? 0 : -1}
            className={`lp-tabs__tab ${tab === t.key ? "is-active" : ""}`}
            onClick={() => setTab(t.key)}
            onKeyDown={(event) => {
              const nextIndex = event.key === "ArrowRight" ? (index + 1) % TABS.length
                : event.key === "ArrowLeft" ? (index - 1 + TABS.length) % TABS.length
                : event.key === "Home" ? 0
                : event.key === "End" ? TABS.length - 1 : -1;
              if (nextIndex < 0) return;
              event.preventDefault();
              setTab(TABS[nextIndex].key);
              tabRefs.current[nextIndex]?.focus();
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`${base}-panel-${tab}`} aria-labelledby={`${base}-tab-${tab}`} className="lp-tabs__panel">
        {tab === "transcript" && <TranscriptTab />}
        {tab === "dialect" && <DialectTab />}
        {tab === "rag" && <RagTab />}
      </div>
      <p className="lp-tabs__note">Sample data, for illustration — your own runs use your prompt and documents.</p>
    </div>
  );
}

/** Demo transcript, opened on the turn that broke a rule. */
function TranscriptTab() {
  // Default to the turn that broke a rule so the point is visible immediately.
  const brokeIdx = DEMO_TURNS.findIndex((t) => t.broke);
  const [sel, setSel] = useState(brokeIdx === -1 ? 0 : brokeIdx);
  const turn = DEMO_TURNS[sel];
  return (
    <div className="lp-trans">
      <ul className="lp-trans__turns">
        {DEMO_TURNS.map((t, i) => (
          <li key={i}>
            <button
              type="button"
              className={`lp-trans__turn lp-trans__turn--${t.speaker} ${sel === i ? "is-sel" : ""} ${t.broke ? "has-break" : ""}`}
              onClick={() => setSel(i)}
              aria-pressed={sel === i}
            >
              <span className="lp-trans__who">{t.speaker === "caller" ? "Caller" : "Agent"}</span>
              <span className="lp-trans__text">{t.text}</span>
              {t.broke && <span className="lp-trans__flag" aria-label="broke a rule" />}
            </button>
          </li>
        ))}
      </ul>
      <div className="lp-trans__detail">
        {turn.broke ? (
          <p className="lp-trans__broke">
            <strong>Rule broken.</strong> {turn.broke}
          </p>
        ) : (
          <p className="lp-trans__ok">This turn kept the rules. Click the flagged agent turn to see what broke.</p>
        )}
        <p className="lp-demo__label">Rubric dimensions</p>
        <ul className="lp-dims">
          {DEMO_DIMENSIONS.map((d) => (
            <li key={d.key} className="lp-dim">
              <span className="lp-dim__label">{d.label}</span>
              <span className="lp-dim__pips" role="img" aria-label={`${d.score} of 5`}>
                {Array.from({ length: 5 }, (_, i) => (
                  <span key={i} className={`lp-dim__pip ${i < d.score ? "is-on" : ""} ${d.score <= 1 ? "is-bad" : ""}`} />
                ))}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** Demo word error rate per dialect, scaled to the worst one. */
function DialectTab() {
  const max = Math.max(...DEMO_DIALECT.map((d) => d.wer));
  return (
    <div className="lp-dialect">
      <ul className="lp-dialect__rows">
        {DEMO_DIALECT.map((d) => (
          <li key={d.dialect} className="lp-dialect__row">
            <span className="lp-dialect__name">{d.dialect}</span>
            <span className="lp-dialect__bar">
              <span className={`lp-dialect__fill ${d.wer >= 0.2 ? "is-high" : d.wer >= 0.13 ? "is-mid" : ""}`} style={{ width: `${(d.wer / max) * 100}%` }} />
            </span>
            <span className="lp-dialect__val mono">{(d.wer * 100).toFixed(0)}% WER</span>
            <span className="lp-dialect__n mono">n={d.n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Demo comparison of retrieval setups, with the last (best) row highlighted. */
function RagTab() {
  return (
    <div className="lp-rag">
      <table className="lp-rag__table">
        <thead>
          <tr>
            <th scope="col">Retrieval setup</th>
            <th scope="col">Pass rate</th>
            <th scope="col">Mean score</th>
          </tr>
        </thead>
        <tbody>
          {DEMO_RAG.map((r, i) => (
            <tr key={r.setup} className={i === DEMO_RAG.length - 1 ? "is-best" : ""}>
              <td>{r.setup}</td>
              <td className="mono">{Math.round(r.passRate * 100)}%</td>
              <td className="mono">{r.scoreMean.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="lp-rag__hint">Each setup is run on the same scenarios, so the winner is the one that actually grounds its answers.</p>
    </div>
  );
}
