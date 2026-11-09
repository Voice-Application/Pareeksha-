"use client";

import type { ReactNode } from "react";
import { AuthDisabledContext } from "./providers";
import { AppShell } from "./layout/app-shell";

export function DashboardAuth({ children, authDisabled }: { children: ReactNode; authDisabled: boolean }) {
  return <AuthDisabledContext.Provider value={authDisabled}><AppShell>{children}</AppShell></AuthDisabledContext.Provider>;
}
