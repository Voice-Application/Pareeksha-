"use client";

import { useState } from "react";

/** The quick-start commands, each with a copy button. The button says what happened; nothing else changes. */
export function CopySteps({ steps }: { steps: string[] }) {
  const [state, setState] = useState<{ i: number; ok: boolean } | null>(null);
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
              navigator.clipboard
                ?.writeText(cmd)
                .then(() => setState({ i, ok: true }), () => setState({ i, ok: false }))
                .finally(() => window.setTimeout(() => setState((s) => (s?.i === i ? null : s)), 1600));
            }}
          >
            {state?.i === i ? (state.ok ? "Copied" : "Select and copy") : "Copy"}
          </button>
        </li>
      ))}
    </ol>
  );
}
