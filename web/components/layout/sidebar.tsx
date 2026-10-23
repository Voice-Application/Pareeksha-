"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Primary"
      className="shrink-0 border-r border-border bg-surface p-4"
      style={{ width: "var(--sidebar-width)" }}
    >
      <p className="mb-4 font-mono text-sm">Pareeksha</p>
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname === item.href;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "block rounded-base px-2 py-1 text-sm",
                  active ? "bg-accent text-accent-text" : "text-text hover:bg-border",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
