"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  AudioLines,
  BookOpen,
  Bot,
  CirclePlay,
  FileAudio,
  FlaskConical,
  GitCompareArrows,
  IndianRupee,
  Inbox,
  KeyRound,
  Languages,
  LayoutDashboard,
  ListChecks,
  Plug,
  Scale,
  ShieldCheck,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import { NAV_ITEMS, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { useRole } from "./theme-toggle";

const GROUPS: NavItem["group"][] = [null, "Build", "Evaluate", "Operate"];

/** One icon per destination, all from Lucide at 16px on a 1.6 stroke. */
const ICONS: Record<string, LucideIcon> = {
  "/": LayoutDashboard,
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
  "/settings/users": UserCog,
};

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const raw = usePathname();
  const role = useRole();
  // A call is reached from a run, so Runs stays lit on /calls/[id].
  const pathname = raw.startsWith("/calls/") ? "/runs" : raw;
  // The most specific matching item is active, so /runs/new does not also light up Runs.
  const match = NAV_ITEMS.filter((i) => (i.href === "/" ? pathname === "/" : pathname === i.href || pathname.startsWith(i.href + "/"))).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
  return (
    <nav aria-label="Primary" className="flex h-full flex-col gap-6 overflow-y-auto px-3 pt-5 pb-4">
      <Link href="/welcome" onClick={onNavigate} className="block rounded-sm px-3 py-1" aria-label="Pareeksha, about the product">
        <span className="display block text-lg leading-6">Pareeksha</span>
        <span className="block text-xs text-subtle">Voice-agent testing</span>
      </Link>
      {GROUPS.map((group) => (
        <div key={group ?? "top"} className="flex flex-col gap-1">
          {group && <p className="px-3 pb-1 text-xs text-subtle">{group}</p>}
          <ul className="flex flex-col gap-px">
            {NAV_ITEMS.filter((i) => i.group === group && (!i.adminOnly || role !== "member")).map((item) => {
              const active = match?.href === item.href;
              const Icon = ICONS[item.href];
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex h-9 items-center gap-3 rounded-sm px-3 text-sm whitespace-nowrap transition-colors duration-150",
                      active ? "bg-selected text-fg" : "text-muted hover:bg-hover hover:text-fg",
                    )}
                  >
                    {Icon && <Icon size={16} strokeWidth={1.6} className={cn("shrink-0", active ? "text-accent-fg" : "text-subtle")} aria-hidden />}
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
