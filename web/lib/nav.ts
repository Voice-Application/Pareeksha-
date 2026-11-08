/**
 * Sidebar information architecture. The top group is what most people need (test a prompt, add
 * documents, read results, set the AI key); everything else sits under the folded "Advanced"
 * section, still grouped as Build / Evaluate / Operate. Routes = FR-DB-1.
 */
export type NavGroup = "Build" | "Evaluate" | "Operate";
export type NavItem = { href: string; label: string; group: NavGroup | null; adminOnly?: true };

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Home", group: null },
  { href: "/test", label: "Test my prompt", group: null },
  { href: "/knowledge-bases", label: "Documents", group: null },
  { href: "/runs", label: "Results", group: null },
  { href: "/settings/llm", label: "AI settings", group: null, adminOnly: true },
  { href: "/designer", label: "Test designer", group: "Build" },
  { href: "/agents", label: "Agents", group: "Build" },
  { href: "/scenarios", label: "Scenarios", group: "Build" },
  { href: "/personas", label: "Personas", group: "Build" },
  { href: "/noise-profiles", label: "Noise profiles", group: "Build" },
  { href: "/runs/new", label: "New run", group: "Evaluate" },
  { href: "/runs/compare", label: "Run compare", group: "Evaluate" },
  { href: "/audits", label: "Audits", group: "Evaluate" },
  { href: "/rag-lab", label: "RAG lab", group: "Evaluate" },
  { href: "/dialect", label: "Dialect", group: "Evaluate" },
  { href: "/regression", label: "Regression", group: "Evaluate" },
  { href: "/integrations", label: "Integrations", group: "Operate" },
  { href: "/dlq", label: "DLQ", group: "Operate" },
  { href: "/calibration", label: "Calibration", group: "Operate" },
  { href: "/settings/pricing", label: "Pricing", group: "Operate" },
  { href: "/settings/api-keys", label: "API keys", group: "Operate" },
  { href: "/settings/users", label: "Users", group: "Operate", adminOnly: true },
];

export const ADVANCED_GROUPS: NavGroup[] = ["Build", "Evaluate", "Operate"];

/** The most specific item for a path (a call belongs to Results; a test to Test my prompt). */
export function activeItem(pathname: string): NavItem | undefined {
  const path = pathname.startsWith("/calls/") ? "/runs" : pathname;
  return NAV_ITEMS.filter((i) => (i.href === "/" ? path === "/" : path === i.href || path.startsWith(i.href + "/"))).sort((a, b) => b.href.length - a.href.length)[0];
}
