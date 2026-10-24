/** Sidebar information architecture (docs/design/pages/00-shared.md section 2). Routes = FR-DB-1. */
export type NavItem = { href: string; label: string; group: "Build" | "Evaluate" | "Operate" | null };

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", group: null },
  { href: "/agents", label: "Agents", group: "Build" },
  { href: "/scenarios", label: "Scenarios", group: "Build" },
  { href: "/personas", label: "Personas", group: "Build" },
  { href: "/noise-profiles", label: "Noise profiles", group: "Build" },
  { href: "/runs", label: "Runs", group: "Evaluate" },
  { href: "/runs/new", label: "New run", group: "Evaluate" },
  { href: "/runs/compare", label: "Run compare", group: "Evaluate" },
  { href: "/audits", label: "Audits", group: "Evaluate" },
  { href: "/dialect", label: "Dialect", group: "Evaluate" },
  { href: "/regression", label: "Regression", group: "Evaluate" },
  { href: "/integrations", label: "Integrations", group: "Operate" },
  { href: "/dlq", label: "DLQ", group: "Operate" },
  { href: "/calibration", label: "Calibration", group: "Operate" },
  { href: "/settings/api-keys", label: "API keys", group: "Operate" },
];
