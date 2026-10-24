"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";

/** Active agents for selects (scenario agent, generate sheet). One page of up to 200 is enough for a picker. */
export function useAgentOptions() {
  return useQuery({
    queryKey: ["agent-options"],
    queryFn: () => call(api.GET("/api/v1/agents", { params: { query: { limit: 200 } } })),
    select: (page) => page.items ?? [],
  });
}
