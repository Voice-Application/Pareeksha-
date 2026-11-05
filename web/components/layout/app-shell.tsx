"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { LogOut, Menu, X } from "lucide-react";
import { ThemeToggle, useRole } from "./theme-toggle";
import { Sidebar } from "./sidebar";
import { Button } from "@/components/ui/button";
import { ToastProvider } from "@/components/ui/toast";
import { NAV_ITEMS } from "@/lib/nav";

/** Shown only after a password sign-in. The form posts, so signing out works without script too. */
function SignOut() {
  if (!useRole()) return null;
  return (
    <form method="post" action="/api/auth/logout">
      <Button type="submit" variant="ghost" className="px-3">
        <LogOut size={16} strokeWidth={1.6} aria-hidden />
        Sign out
      </Button>
    </form>
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

  // The product and sign-in pages stand outside the working shell: no sidebar, their own chrome.
  if (pathname === "/welcome" || pathname === "/login") return <ToastProvider>{children}</ToastProvider>;

  return (
    <ToastProvider>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-sm focus:bg-surface focus:p-2">
        Skip to content
      </a>
      <div className="min-h-dvh">
        <aside className="fixed inset-y-0 left-0 z-20 hidden border-r border-border bg-sunken min-[861px]:block" style={{ width: "var(--sidebar-w)" }}>
          <Sidebar />
        </aside>
        <dialog
          ref={dlg}
          className="sheet"
          style={{ marginLeft: 0, marginRight: "auto", width: "min(288px, 100%)", background: "var(--bg-sunken)" }}
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
        <div className="flex min-h-dvh min-w-0 flex-col min-[861px]:pl-[var(--sidebar-w)]">
          <header className="sticky top-0 z-10 flex h-14 items-center gap-2 border-b border-border bg-canvas px-4 min-[861px]:px-10">
            <Button variant="ghost" icon aria-label="Open navigation" className="min-[861px]:hidden" onClick={() => setOpen(true)}>
              <Menu size={16} strokeWidth={1.6} aria-hidden />
            </Button>
            <p className="truncate text-sm text-muted">{current?.label ?? (pathname === "/" ? "Overview" : "")}</p>
            <div className="ml-auto flex items-center gap-1">
              <SignOut />
              <ThemeToggle />
            </div>
          </header>
          <main id="main" className="mx-auto w-full max-w-[1360px] flex-1 px-4 pt-8 pb-16 min-[561px]:px-10">
            {children}
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
