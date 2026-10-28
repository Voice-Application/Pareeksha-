"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, Moon, Sun, X } from "lucide-react";
import { Sidebar } from "./sidebar";
import { Button } from "@/components/ui/button";
import { ToastProvider } from "@/components/ui/toast";
import { NAV_ITEMS } from "@/lib/nav";

type Theme = "light" | "dark";

function subscribeTheme(cb: () => void) {
  const o = new MutationObserver(cb);
  o.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => o.disconnect();
}

function ThemeToggle() {
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

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const dlg = useRef<HTMLDialogElement>(null);
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    setLastPath(pathname);
    setOpen(false);
  }
  useEffect(() => {
    const d = dlg.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const current = NAV_ITEMS.filter((i) => i.href !== "/" && (pathname.startsWith("/calls/") ? i.href === "/runs" : pathname === i.href || pathname.startsWith(i.href + "/"))).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];

  return (
    <ToastProvider>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2">
        Skip to content
      </a>
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen shrink-0 border-r border-border bg-surface min-[861px]:block" style={{ width: "var(--sidebar-w)" }}>
          <Sidebar />
        </aside>
        <dialog
          ref={dlg}
          className="sheet"
          style={{ marginLeft: 0, marginRight: "auto", width: "min(280px, 100vw)", borderLeft: 0, borderRight: "1px solid var(--border)" }}
          aria-label="Navigation"
          onClose={() => setOpen(false)}
          onClick={(e) => e.target === dlg.current && setOpen(false)}
        >
          <div className="flex justify-end p-2">
            <Button variant="ghost" icon aria-label="Close navigation" onClick={() => setOpen(false)}>
              <X size={16} strokeWidth={1.6} aria-hidden />
            </Button>
          </div>
          <Sidebar onNavigate={() => setOpen(false)} />
        </dialog>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 flex h-12 items-center gap-2 border-b border-border bg-canvas px-4 min-[861px]:px-8">
            <Button variant="ghost" icon aria-label="Open navigation" className="min-[861px]:hidden" onClick={() => setOpen(true)}>
              <Menu size={16} strokeWidth={1.6} aria-hidden />
            </Button>
            <p className="text-sm text-muted">{current?.label ?? ""}</p>
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </header>
          <main id="main" className="mx-auto w-full max-w-[1360px] flex-1 px-4 py-6 min-[561px]:px-8">
            {children}
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
