"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import {
  Activity,
  AudioLines,
  BookOpen,
  Bot,
  ChevronRight,
  CirclePlay,
  Cpu,
  FileAudio,
  FlaskConical,
  GitCompareArrows,
  House,
  IndianRupee,
  Inbox,
  KeyRound,
  Languages,
  ListChecks,
  MessageSquareText,
  Plug,
  Scale,
  ShieldCheck,
  SquareCheckBig,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import { ADVANCED_GROUPS, NAV_ITEMS, activeItem, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { useRole } from "./theme-toggle";

const ADVANCED_STORE = "pareeksha.nav.advanced";

/** One icon per destination, all from Lucide at 16px on a 1.6 stroke. */
const ICONS: Record<string, LucideIcon> = {
  "/": House,
  "/test": SquareCheckBig,
  "/designer": MessageSquareText,
  "/agents": Bot,
  "/scenarios": ListChecks,
  "/personas": Users,
  "/noise-profiles": AudioLines,
  "/knowledge-bases": BookOpen,
  "/rag-lab": FlaskConical,
  "/settings/pricing": IndianRupee,
  "/runs": Activity,
  "/runs/new": CirclePlay,
  "/runs/compare": GitCompareArrows,
  "/audits": FileAudio,
  "/dialect": Languages,
  "/regression": ShieldCheck,
  "/integrations": Plug,
  "/dlq": Inbox,
  "/calibration": Scale,
  "/settings/api-keys": KeyRound,
  "/settings/llm": Cpu,
  "/settings/users": UserCog,
};

const CHANGED = "pareeksha:nav-advanced";

/** The folded section's state lives in localStorage; the server (and first paint) render it closed. */
function readAdvanced(): boolean {
  try {
    return window.localStorage.getItem(ADVANCED_STORE) === "1";
  } catch {
    return false;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

function writeAdvanced(open: boolean) {
  try {
    window.localStorage.setItem(ADVANCED_STORE, open ? "1" : "0");
  } catch {
    /* convenience only */
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const role = useRole();
  const match = activeItem(pathname);
  const openPref = useSyncExternalStore(subscribe, readAdvanced, () => false);
  // The section opens by itself when the current page lives in it.
  const inside = (match?.group ?? null) !== null;
  const open = openPref || inside;
  const visible = (i: NavItem) => !i.adminOnly || role !== "member";
  const toggle = () => writeAdvanced(!open);

  const item = (it: NavItem) => {
    const active = match?.href === it.href;
    const Icon = ICONS[it.href];
    return (
      <li key={it.href}>
        <Link
          href={it.href}
          onClick={onNavigate}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex h-9 items-center gap-3 rounded-sm px-3 text-sm whitespace-nowrap transition-colors duration-150",
            active ? "bg-selected text-fg" : "text-muted hover:bg-hover hover:text-fg",
          )}
        >
          {Icon && <Icon size={16} strokeWidth={1.6} className={cn("shrink-0", active ? "text-accent-fg" : "text-subtle")} aria-hidden />}
          {it.label}
        </Link>
      </li>
    );
  };

  return (
    <nav aria-label="Primary" className="flex h-full flex-col gap-6 overflow-y-auto px-3 pt-5 pb-4">
      <Link href="/welcome" onClick={onNavigate} className="block rounded-sm px-3 py-1" aria-label="Pareeksha, about the product">
        <span className="display block text-lg leading-6">Pareeksha</span>
        <span className="block text-xs text-subtle">Test your bots before customers do</span>
      </Link>
      <ul className="flex flex-col gap-px">{NAV_ITEMS.filter((i) => i.group === null && visible(i)).map(item)}</ul>
      <div className="flex flex-col gap-3 border-t border-border pt-4">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="nav-advanced"
          onClick={toggle}
          className="flex h-8 items-center gap-2 rounded-sm px-3 text-left text-sm text-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <ChevronRight size={14} strokeWidth={1.6} className={cn("shrink-0 transition-transform duration-150", open && "rotate-90")} aria-hidden />
          Advanced
        </button>
        {open && (
          <div id="nav-advanced" className="flex flex-col gap-5">
            {ADVANCED_GROUPS.map((group) => (
              <div key={group} className="flex flex-col gap-1">
                <p className="px-3 pb-1 text-xs text-subtle">{group}</p>
                <ul className="flex flex-col gap-px">{NAV_ITEMS.filter((i) => i.group === group && visible(i)).map(item)}</ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
