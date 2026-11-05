"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Ellipsis } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export type MenuItem = { label: string; onSelect: () => void; destructive?: boolean; disabled?: boolean };

/** Trailing "..." menu. Enter/Space/ArrowDown open it, arrows move, Esc closes and returns focus to the trigger. */
export function RowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  const measureMenu = useCallback((el: HTMLDivElement | null) => {
    menu.current = el;
    if (!el || !trigger.current) return;
    const anchor = trigger.current.getBoundingClientRect();
    const bounds = el.getBoundingClientRect();
    const gap = 4;
    const below = anchor.bottom + gap;
    const top = below + bounds.height <= window.innerHeight - gap ? below : anchor.top - gap - bounds.height;
    setPos({
      top: Math.max(gap, Math.min(top, window.innerHeight - bounds.height - gap)),
      left: Math.max(gap, Math.min(anchor.right - bounds.width, window.innerWidth - bounds.width - gap)),
    });
  }, []);

  useEffect(() => {
    if (!open || !pos) return;
    const first = menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)");
    first?.focus();
    const onDown = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !trigger.current?.contains(e.target as Node)) setOpen(false);
    };
    const onScroll = (e: Event) => {
      if (!(e.target instanceof Node) || !menu.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, pos]);

  function close(refocus = true) {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }

  function onMenuKey(e: React.KeyboardEvent) {
    const btns = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    const i = btns.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      btns[(i + 1) % btns.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      btns[(i - 1 + btns.length) % btns.length]?.focus();
    } else if (e.key === "Tab") setOpen(false);
  }

  return (
    <>
      <Button
        ref={trigger}
        variant="ghost"
        icon
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        className="h-9 w-9"
        onClick={() => {
          setPos(null);
          setOpen((o) => !o);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            (e.currentTarget as HTMLButtonElement).click();
          }
        }}
      >
        <Ellipsis size={16} strokeWidth={1.6} aria-hidden />
      </Button>
      {open && (
        <div
          ref={measureMenu}
          id={id}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKey}
          className="fixed z-40 w-max min-w-[min(160px,calc(100vw-8px))] max-w-[calc(100vw-8px)] max-h-[calc(100vh-8px)] overflow-auto rounded-md border border-border bg-surface p-1"
          style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden", boxShadow: "var(--shadow-float)" }}
        >
          {items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              type="button"
              disabled={it.disabled}
              onClick={() => {
                close(false);
                it.onSelect();
              }}
              className={cn("flex h-9 w-full items-center rounded-sm px-2 text-left text-sm hover:bg-hover focus:bg-hover disabled:opacity-50", it.destructive && "text-fail-fg")}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
