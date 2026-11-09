"use client";

import { useContext, useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SIGNED_IN_COOKIE } from "@/lib/session";

import { AuthDisabledContext } from "@/components/providers";

type Theme = "light" | "dark";

function subscribeTheme(cb: () => void) {
  const o = new MutationObserver(cb);
  o.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => o.disconnect();
}

export function ThemeToggle() {
  const theme = useSyncExternalStore<Theme>(
    subscribeTheme,
    () => (document.documentElement.classList.contains("dark") ? "dark" : "light"),
    () => "light",
  );
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <Button
      variant="ghost"
      icon
      aria-label={`Switch to ${next} theme`}
      onClick={() => {
        document.documentElement.classList.toggle("dark", next === "dark");
        try {
          localStorage.setItem("theme", next);
        } catch {
          /* storage may be blocked; the choice then lasts for this page view */
        }
      }}
    >
      {theme === "dark" ? <Sun size={16} strokeWidth={1.6} aria-hidden /> : <Moon size={16} strokeWidth={1.6} aria-hidden />}
    </Button>
  );
}

function subscribeRole(cb: () => void) {
  // Cookie changes can come from another tab or an HTTP response. Older browsers need polling.
  const store = "cookieStore" in window ? window.cookieStore : undefined;
  store?.addEventListener("change", cb);
  const timer = store ? undefined : window.setInterval(cb, 1000);
  window.addEventListener("focus", cb);
  document.addEventListener("visibilitychange", cb);
  return () => {
    store?.removeEventListener("change", cb);
    window.clearInterval(timer);
    window.removeEventListener("focus", cb);
    document.removeEventListener("visibilitychange", cb);
  };
}

/** The signed-in role from the readable cookie, for showing or hiding links only. Access is enforced by the server. */
export function useRole(): string | null {
  return useSyncExternalStore(
    subscribeRole,
    () => document.cookie.split("; ").find((c) => c.startsWith(`${SIGNED_IN_COOKIE}=`))?.split("=")[1] ?? null,
    () => null,
  );
}

/** Show admin controls in open-dashboard mode, or for an explicit admin role when sign-in is enabled. */
export function useIsAdmin(): boolean {
  const role = useRole();
  const authDisabled = useContext(AuthDisabledContext);
  return authDisabled || role === "admin";
}
