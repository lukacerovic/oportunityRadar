"use client";

import { useMemo, useState } from "react";
import { titleize } from "@/lib/format";

// Shared overwhelm-fix for long flat lists (Changes/Gate pages routinely carry 300-1000+ rows).
// Groups by an existing taxonomy field (category — no new taxonomy invented) and adds a
// client-side text filter. Large groups start collapsed; a live search auto-expands matches.
interface GroupedListProps<T> {
  items: T[];
  getCategory: (item: T) => string | null;
  getSearchText: (item: T) => string;
  renderItem: (item: T) => React.ReactNode;
  keyOf: (item: T) => string | number;
  collapseAbove?: number;
  itemLabel?: string;
}

export function GroupedList<T>({
  items,
  getCategory,
  getSearchText,
  renderItem,
  keyOf,
  collapseAbove = 8,
  itemLabel = "items",
}: GroupedListProps<T>) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => {
      const cat = getCategory(it) ?? "";
      return getSearchText(it).toLowerCase().includes(q) || cat.toLowerCase().includes(q);
    });
  }, [items, query, getSearchText, getCategory]);

  const groups = useMemo(() => {
    const m = new Map<string, T[]>();
    for (const it of filtered) {
      const cat = getCategory(it) ?? "uncategorized";
      (m.get(cat) ?? m.set(cat, []).get(cat)!).push(it);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [filtered, getCategory]);

  const searching = query.trim().length > 0;

  return (
    <div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={`Filter ${itemLabel} by name or category…`}
        className="mb-3 w-full max-w-sm rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-accent"
      />
      {filtered.length === 0 && (
        <div className="py-4 text-center text-xs text-faint">
          No {itemLabel} match &ldquo;{query}&rdquo;.
        </div>
      )}
      <div className="space-y-2">
        {groups.map(([cat, groupItems]) => {
          const defaultOpen = searching || groupItems.length <= collapseAbove;
          // `open` as a plain prop can't stay in sync with a user manually toggling the native
          // <details> element — React only writes it when the computed value itself changes
          // across renders. Keying on the computed default forces a remount (not a reconcile)
          // whenever search state changes the intended default, so a stale manual toggle from
          // before the search never lingers against the new default.
          return (
            <details key={`${cat}-${defaultOpen}`} open={defaultOpen} className="group">
              <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-muted transition hover:bg-card-hover">
                <span className="inline-block text-faint transition-transform group-open:rotate-90">▸</span>
                {titleize(cat)}
                <span className="tabular text-faint">{groupItems.length}</span>
              </summary>
              <div className="mt-1.5 space-y-1.5 pl-1">
                {groupItems.map((it) => (
                  <div key={keyOf(it)}>{renderItem(it)}</div>
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}
