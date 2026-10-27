"use client";

import { useEffect, useState } from "react";

/** Current time in ms, refreshed on an interval (keeps render pure; 0 until mounted). */
export function useNow(everyMs = 5000): number {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const t = setInterval(tick, everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}
