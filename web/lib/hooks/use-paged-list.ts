"use client";

import { useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

type Page<T> = { items: T[]; next_cursor?: string | null };

/** Cursor-paginated list ("Load more", 00-shared 4). `key` must include every server-side filter. */
export function usePagedList<T>(key: readonly unknown[], fetchPage: (cursor: string | null) => Promise<Page<T>>) {
  const q = useInfiniteQuery({
    queryKey: key,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = useMemo(() => q.data?.pages.flatMap((p) => p.items ?? []) ?? [], [q.data]);
  return { ...q, items };
}
