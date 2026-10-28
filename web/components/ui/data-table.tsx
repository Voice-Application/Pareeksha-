"use client";

import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Search, X } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";
import { controlClass } from "./field";

export type Column<T> = {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Sortable columns need an entry with the same key in the page's `sorters` map. */
  sortable?: boolean;
  mono?: boolean;
  className?: string;
  /** Hidden on phone cards (name, key status, key number stay). */
  hidePhone?: boolean;
};

/** Parse "key:asc" / "key:desc" from the URL. */
export function parseSort(raw: string): { key: string; dir: "asc" | "desc" } | null {
  const [key, dir] = raw.split(":");
  return key && (dir === "asc" || dir === "desc") ? { key, dir } : null;
}

export type Sorters<T> = Record<string, (row: T) => string | number | null>;

export function sortRows<T>(rows: T[], sorters: Sorters<T>, sort: { key: string; dir: "asc" | "desc" } | null): T[] {
  if (!sort) return rows;
  const sv = sorters[sort.key];
  if (!sv) return rows;
  const sign = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = sv(a);
    const y = sv(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1; // dashes last in both directions
    if (y === null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * sign;
  });
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  sort,
  onSort,
  actions,
}: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sort: { key: string; dir: "asc" | "desc" } | null;
  onSort: (next: string | null) => void;
  /** Trailing cell (row menu). */
  actions?: (row: T) => ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="rt">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              return (
                <th key={c.key} scope="col" aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined} className={c.hidePhone ? "rt-hide-phone" : undefined}>
                  {c.sortable ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 rounded-xs hover:text-fg"
                      onClick={() => onSort(!active ? `${c.key}:asc` : sort.dir === "asc" ? `${c.key}:desc` : null)}
                    >
                      {c.header}
                      {active ? sort.dir === "asc" ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden /> : <ArrowUpDown size={12} className="text-subtle" aria-hidden />}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
            {actions && (
              <th scope="col" className="w-12">
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c, i) => (
                <td key={c.key} data-label={i === 0 ? "" : c.header} className={cn(c.mono && "mono", c.className, c.hidePhone && "rt-hide-phone")}>
                  {c.cell(row)}
                </td>
              ))}
              {actions && (
                <td data-label="" className="rt-actions text-right">
                  {actions(row)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Search input + filter selects + active-filter chips + Clear. */
export function FilterBar({
  search,
  onSearch,
  placeholder,
  children,
  chips,
  onClear,
}: {
  search: string;
  onSearch: (v: string) => void;
  placeholder: string;
  children?: ReactNode;
  chips: { label: string; remove: () => void }[];
  onClear: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-b border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-[320px]">
          <Search size={14} strokeWidth={1.6} className="pointer-events-none absolute left-2 top-2.5 text-subtle" aria-hidden />
          <input
            type="search"
            aria-label={placeholder}
            placeholder={placeholder}
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className={cn(controlClass, "pl-7")}
          />
        </div>
        {children}
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
          {chips.map((c) => (
            <span key={c.label} className="inline-flex h-6 items-center gap-1 rounded-xs border border-border bg-sunken pl-2 pr-0.5 text-xs">
              {c.label}
              <button type="button" aria-label={`Remove filter ${c.label}`} onClick={c.remove} className="flex h-5 w-5 items-center justify-center rounded-xs hover:bg-hover">
                <X size={12} strokeWidth={1.6} aria-hidden />
              </button>
            </span>
          ))}
          <Button variant="ghost" className="h-6 px-2" onClick={onClear}>
            Clear
          </Button>
        </div>
      )}
    </div>
  );
}

export function LoadMore({ hasMore, loading, onClick, shown }: { hasMore: boolean; loading: boolean; onClick: () => void; shown: number }) {
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs text-subtle">
      <span>
        <span className="mono">{shown}</span> loaded
      </span>
      {hasMore && (
        <Button loading={loading} onClick={onClick}>
          Load more
        </Button>
      )}
    </div>
  );
}
