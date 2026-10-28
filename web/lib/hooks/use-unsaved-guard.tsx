"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ConfirmDialog } from "@/components/ui/overlay";

/**
 * Leaving a form with changes asks first (agents spec, "Unsaved changes"). Covers in-app link clicks and tab close.
 * Call `release()` right before a deliberate navigation (after a successful save).
 */
export function useUnsavedGuard(dirty: boolean): { dialog: ReactNode; release: () => void } {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const bypass = useRef(false);

  useEffect(() => {
    if (!dirty) return;
    const onBefore = (e: BeforeUnloadEvent) => {
      if (bypass.current) return;
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (bypass.current || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const a = (e.target as HTMLElement).closest("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin) return;
      if (u.pathname + u.search === location.pathname + location.search) return;
      e.preventDefault();
      e.stopPropagation();
      setPending(u.pathname + u.search);
    };
    window.addEventListener("beforeunload", onBefore);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBefore);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);

  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      onClose={() => setPending(null)}
      title="Leave without saving?"
      body="Your changes to this form have not been saved."
      confirmLabel="Leave page"
      onConfirm={() => {
        bypass.current = true;
        const to = pending;
        setPending(null);
        if (to) router.push(to);
      }}
    />
  );
  return {
    dialog,
    release: () => {
      bypass.current = true;
    },
  };
}
