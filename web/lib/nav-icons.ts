import {
  Activity,
  AudioLines,
  BookOpen,
  Bot,
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
import { activeItem } from "@/lib/nav";

/**
 * One icon per destination, all from Lucide. Shared by the sidebar (per-row) and the page header
 * (per-title), so a route shows the same glyph in the nav and at the top of its page.
 */
export const NAV_ICONS: Record<string, LucideIcon> = {
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

/** The icon for a destination href, or undefined if the route has none. */
export function iconFor(href: string): LucideIcon | undefined {
  return NAV_ICONS[href];
}

/** The section icon for a pathname, resolved through the same active-item mapping the sidebar uses. */
export function iconForPath(pathname: string): LucideIcon | undefined {
  const match = activeItem(pathname);
  return match ? NAV_ICONS[match.href] : undefined;
}
