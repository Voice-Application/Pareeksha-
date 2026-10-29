"use client";

import { useCallback, useEffect, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** List filters, sort and search live in the URL so states are shareable (00-shared 6). */
export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  // Two changes made before the router re-renders (Clear, then a select) must build on each other, not on
  // the stale rendered params; the ref holds the newest query and is re-synced whenever the URL changes.
  const latest = useRef(params.toString());
  useEffect(() => {
    latest.current = params.toString();
  }, [params]);

  const get = useCallback((key: string, fallback = "") => params.get(key) ?? fallback, [params]);
  const set = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(latest.current);
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === "") next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      latest.current = qs;
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );
  const clear = useCallback(() => {
    latest.current = "";
    router.replace(pathname, { scroll: false });
  }, [pathname, router]);
  return { get, set, clear, active: params.size > 0 };
}
