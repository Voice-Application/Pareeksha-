"use client";

import { useState } from "react";

/** The quick-start commands, each with a copy button. The result is shown on the button and announced politely. */
export function CopySteps({ steps }: { steps: string[] }) {
  const [state, setState] = useState<{ i: number; ok: boolean } | null>(null);
  const word = (i: number) => (state?.i === i ? (state.ok ? "Copied" : "Select and copy") : "");
  return (
    <ol className="lp-steps">
      {steps.map((cmd, i) => (
        <li key={cmd}>
          <code>{cmd}</code>
          <button
            type="button"
            className="lp-copy"
            aria-label={`Copy command ${i + 1}`}
            onClick={() => {
              // A non-secure origin has no Clipboard API: say so instead of doing nothing.
              (navigator.clipboard ? navigator.clipboard.writeText(cmd) : Promise.reject(new Error("Clipboard API unavailable")))
                .then(() => setState({ i, ok: true }), () => setState({ i, ok: false }))
                .finally(() => window.setTimeout(() => setState((s) => (s?.i === i ? null : s)), 1600));
            }}
          >
            {word(i) || "Copy"}
          </button>
          <span aria-live="polite" className="sr-only">{word(i)}</span>
        </li>
      ))}
    </ol>
  );
}
