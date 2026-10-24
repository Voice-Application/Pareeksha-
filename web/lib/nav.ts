/** Sidebar information architecture. Final grouping/labels come from DES-01. Routes = FR-DB-1. */
export type NavItem = { href: string; label: string };

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview" },
  { href: "/agents", label: "Agents" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/personas", label: "Personas" },
  { href: "/noise-profiles", label: "Noise profiles" },
  { href: "/runs", label: "Runs" },
  { href: "/runs/new", label: "New run" },
  { href: "/runs/compare", label: "Run compare" },
  { href: "/audits", label: "Audits" },
  { href: "/dialect", label: "Dialect" },
  { href: "/regression", label: "Regression" },
  { href: "/integrations", label: "Integrations" },
  { href: "/dlq", label: "DLQ" },
  { href: "/calibration", label: "Calibration" },
  { href: "/settings/api-keys", label: "API keys" },
];
