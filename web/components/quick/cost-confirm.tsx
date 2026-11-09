"use client";

import { inr, type CostEstimate } from "@/lib/api/quick-tests";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { Strip } from "@/components/ui/states";

/**
 * The one "Run this test?" confirmation, shown when the API answers 402 `confirm_cost` because a test
 * is estimated above the auto-run limit. Used by a new test and by re-testing an improved prompt, so
 * both explain the cost the same way. It stays open with the Run button loading until the request
 * succeeds (the caller navigates away) or fails (the error shows here, and the user can retry or back out).
 */
export function CostConfirmDialog({
  estimate,
  onRun,
  onClose,
  running,
  error,
}: {
  /** The 402's estimate; `null` keeps the dialog closed. */
  estimate: CostEstimate | null;
  onRun: () => void;
  onClose: () => void;
  running: boolean;
  error?: string | null;
}) {
  return (
    <Dialog
      open={!!estimate}
      // Closing mid-request would hide the outcome; the Run button is the only way out while it runs.
      onClose={() => {
        if (!running) onClose();
      }}
      title="Run this test?"
      footer={
        <>
          <Button onClick={onClose} disabled={running}>
            Not now
          </Button>
          <Button variant="primary" loading={running} onClick={onRun}>
            Run for {inr(estimate?.est_cost)}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p>
          {estimate?.conversations} conversations are estimated at {inr(estimate?.est_cost)}, above the {inr(estimate?.limit)} that runs without asking. The estimate assumes every conversation runs to its longest, so the real cost is usually lower.
        </p>
        {error && <Strip tone="error">{error}</Strip>}
      </div>
    </Dialog>
  );
}
