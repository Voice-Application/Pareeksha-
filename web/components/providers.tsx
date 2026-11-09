"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useState, type ReactNode } from "react";

export const AuthDisabledContext = createContext(false);

export function Providers({ children, authDisabled }: { children: ReactNode; authDisabled: boolean }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1 } } }));
  return <AuthDisabledContext.Provider value={authDisabled}><QueryClientProvider client={client}>{children}</QueryClientProvider></AuthDisabledContext.Provider>;
}
