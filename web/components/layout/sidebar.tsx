"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useSyncExternalStore } from "react";
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
import { ADVANCED_GROUPS, NAV_ITEMS, SETTINGS_GROUP, activeItem, type NavItem, type NavSection } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { useIsAdmin } from "./theme-toggle";

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

/** What the user chose last: "1" open, "0" closed, "" nothing yet. Kept in memory when storage fails. */
let memoryChoice = "";

/** The folded section's choice lives in localStorage; the server (and first paint) render no choice. */
function readAdvanced(): string {
  try {
    const stored = window.localStorage.getItem(ADVANCED_STORE);
    if (stored === "1" || stored === "0") return stored;
  } catch {
    /* storage blocked: use the in-memory choice */
  }
  return memoryChoice;
}

/** Subscribe to changes of the Advanced choice (this tab and other tabs). */
function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

/** Remember the choice in memory, and in localStorage when it works. */
function writeAdvanced(open: boolean) {
  memoryChoice = open ? "1" : "0";
  try {
    window.localStorage.setItem(ADVANCED_STORE, memoryChoice);
  } catch {
    /* convenience only: the in-memory choice still applies */
  }
  window.dispatchEvent(new Event(CHANGED));
}

/** The left navigation: the core destinations, a foldable Advanced section (Build/Evaluate/Operate),
 *  and a Settings group pinned to the bottom. Admin-only items show only for an explicit admin role. */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const isAdmin = useIsAdmin();
  const match = activeItem(pathname);
  const regionId = useId();
  const choice = useSyncExternalStore(subscribe, readAdvanced, () => "");
  // With no choice yet, the section opens by itself only when the current page lives in Advanced —
  // the Settings group (and the ungrouped core items) must not auto-open it.
  const inside = match?.group != null && (ADVANCED_GROUPS as NavSection[]).includes(match.group);
  const open = choice === "" ? inside : choice === "1";
  // Admin-only items show only for an admin; an unknown/missing role is treated as non-admin (open
  // dashboard mode aside), so a member with a transient cookie gap never sees admin-only links.
  const visible = (i: NavItem) => !i.adminOnly || isAdmin;
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
          aria-controls={regionId}
          onClick={toggle}
          className="flex h-8 items-center gap-2 rounded-sm px-3 text-left text-sm text-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <ChevronRight size={14} strokeWidth={1.6} className={cn("shrink-0 transition-transform duration-150", open && "rotate-90")} aria-hidden />
          Advanced
        </button>
        {open && (
          <div id={regionId} className="flex flex-col gap-5">
            {ADVANCED_GROUPS.map((group) => (
              <div key={group} className="flex flex-col gap-1">
                <p className="px-3 pb-1 text-xs text-subtle">{group}</p>
                <ul className="flex flex-col gap-px">{NAV_ITEMS.filter((i) => i.group === group && visible(i)).map(item)}</ul>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="mt-auto flex flex-col gap-1 border-t border-border pt-4">
        <p className="px-3 pb-1 text-xs text-subtle">{SETTINGS_GROUP}</p>
        <ul className="flex flex-col gap-px">{NAV_ITEMS.filter((i) => i.group === SETTINGS_GROUP && visible(i)).map(item)}</ul>
      </div>
    </nav>
  );
}
