"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Ellipsis } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export type MenuItem = { label: string; onSelect: () => void; destructive?: boolean; disabled?: boolean };

/** Trailing "..." menu. Enter/Space/ArrowDown open it, arrows move, Esc closes and returns focus to the trigger. */
export function RowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number; above: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const first = menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)");
    // Focusing the first item can scroll it into view; ignore scrolls until that settles so the
    // just-opened menu is not closed by its own open (observed as flaky click-to-open in tests).
    let armed = false;
    first?.focus();
    const t = setTimeout(() => (armed = true), 0);
    /** Close on a press outside both the menu and its trigger. */
    const onDown = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !trigger.current?.contains(e.target as Node)) setOpen(false);
    };
    /** Close on scroll once armed, since the portalled menu would detach from its row. */
    const onScroll = () => { if (armed) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  // Flip above the trigger when the measured menu would run past the bottom of the viewport.
  useLayoutEffect(() => {
    const m = menu.current;
    if (!open || !m || !pos) return;
    const h = m.getBoundingClientRect().height;
    if (pos.top + h > window.innerHeight - 8) m.style.top = `${Math.max(8, pos.above - h - 4)}px`;
  }, [open, pos]);

  /** Close the menu, returning focus to the trigger by default. */
  function close(refocus = true) {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }

  /** Menu keys: Escape closes, arrows cycle items, Tab returns focus to the trigger. */
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
    } else if (e.key === "Tab") {
      // The menu is portalled to <body>; hand focus back to the trigger so Tab's default
      // action moves on from the row, not from the end of the document.
      trigger.current?.focus();
      setOpen(false);
    }
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
        onClick={(e) => {
          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
          setPos({ top: r.bottom + 4, right: window.innerWidth - r.right, above: r.top });
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
      {/* Portalled to <body> so an ancestor's transform/opacity animation can neither become the
          fixed menu's containing block (breaking viewport-edge flipping) nor trap its z-index
          beneath the next panel. */}
      {open && pos && createPortal(
        <div
          ref={menu}
          id={id}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKey}
          className="fixed z-40 min-w-[160px] rounded-md border border-border bg-surface p-1"
          style={{ top: pos.top, right: pos.right, boxShadow: "var(--shadow-float)" }}
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
        </div>,
        document.body,
      )}
    </>
  );
}
