"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";

const GROUPS: NavItem["group"][] = [null, "Build", "Evaluate", "Operate"];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  // The most specific matching item is active, so /runs/new does not also light up Runs.
  const match = NAV_ITEMS.filter((i) => (i.href === "/" ? pathname === "/" : pathname === i.href || pathname.startsWith(i.href + "/"))).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
  return (
    <nav aria-label="Primary" className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <p className="mono text-md font-semibold">Pareeksha</p>
      {GROUPS.map((group) => (
        <div key={group ?? "top"}>
          {group && <p className="eyebrow mb-1 px-2">{group}</p>}
          <ul className="flex flex-col gap-0.5">
            {NAV_ITEMS.filter((i) => i.group === group).map((item) => {
              const active = match?.href === item.href;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "block rounded-sm px-2 text-sm leading-8 transition-colors",
                      active ? "bg-selected font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg",
                    )}
                  >
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
