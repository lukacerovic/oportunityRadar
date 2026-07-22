"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { titleize } from "@/lib/format";
import { API_BASE } from "@/lib/api";
import type { RadarEntity, SearchHit } from "@/lib/types";
import { EntityCard } from "./EntityCard";
import { StateChip } from "./StateChip";

type SortKey = "momentum" | "velocity" | "name";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "momentum", label: "Momentum" },
  { key: "velocity", label: "Velocity" },
  { key: "name", label: "Name (A–Z)" },
];

// Unique, sorted, non-null values of a field across the loaded entities.
function options(entities: RadarEntity[], field: "entity_type" | "category" | "maturity_stage") {
  const seen = new Set<string>();
  for (const e of entities) {
    const v = e[field];
    if (v) seen.add(v);
  }
  return Array.from(seen).sort();
}

export function RadarGrid({ entities }: { entities: RadarEntity[] }) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [category, setCategory] = useState("all");
  const [stage, setStage] = useState("all");
  const [sort, setSort] = useState<SortKey>("momentum");

  const term = query.trim();
  // A name search hits the whole DB via /search — the loaded grid is only the top-240 by momentum,
  // so dormant entities (e.g. a fresh launch like Kimi) would otherwise be unfindable here.
  const searchMode = term.length >= 2;

  const types = useMemo(() => options(entities, "entity_type"), [entities]);
  const categories = useMemo(() => options(entities, "category"), [entities]);
  const stages = useMemo(() => options(entities, "maturity_stage"), [entities]);

  const filtered = useMemo(() => {
    const out = entities.filter((e) => {
      if (type !== "all" && e.entity_type !== type) return false;
      if (category !== "all" && e.category !== category) return false;
      if (stage !== "all" && e.maturity_stage !== stage) return false;
      return true;
    });
    if (sort === "velocity") {
      return [...out].sort((a, b) => (b.velocity_pctl ?? -1) - (a.velocity_pctl ?? -1));
    }
    if (sort === "name") {
      return [...out].sort((a, b) => a.name.localeCompare(b.name));
    }
    return out; // "momentum" = keep server order
  }, [entities, type, category, stage, sort]);

  const filtersActive = type !== "all" || category !== "all" || stage !== "all";

  const clearFilters = () => {
    setType("all");
    setCategory("all");
    setStage("all");
    setSort("momentum");
  };

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search all entities by name…"
            className="w-full rounded-lg border border-border bg-surface py-1.5 pl-9 pr-8 text-sm text-text placeholder:text-faint focus:border-accent-dim focus:outline-none"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-faint hover:text-text"
            >
              ✕
            </button>
          )}
        </div>

        {/* Browse filters only make sense over the loaded momentum grid, not a name search. */}
        {!searchMode && (
          <>
            <Select label="Type" value={type} onChange={setType} options={types} />
            <Select label="Category" value={category} onChange={setCategory} options={categories} />
            <Select label="Stage" value={stage} onChange={setStage} options={stages} />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:border-accent-dim focus:outline-none"
              aria-label="Sort by"
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  Sort: {s.label}
                </option>
              ))}
            </select>
            {filtersActive && (
              <button
                onClick={clearFilters}
                className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition hover:text-text"
              >
                Clear
              </button>
            )}
          </>
        )}
      </div>

      {searchMode ? (
        <SearchResults term={term} />
      ) : (
        <>
          <div className="mb-3 text-xs text-faint">
            {filtered.length === entities.length
              ? `${entities.length} entities`
              : `${filtered.length} of ${entities.length} entities`}
          </div>
          {filtered.length === 0 ? (
            <div className="panel p-10 text-center text-sm text-muted">
              No entities match these filters.{" "}
              <button onClick={clearFilters} className="text-accent hover:underline">
                Clear filters
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filtered.map((e) => (
                <EntityCard key={e.id} e={e} />
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}

function SearchResults({ term }: { term: string }) {
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    // Debounce so we don't fire a request per keystroke.
    const t = setTimeout(() => {
      fetch(`${API_BASE}/search?q=${encodeURIComponent(term)}&limit=50`, { signal: ctrl.signal })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API ${r.status}`))))
        .then((data: SearchHit[]) => setHits(data))
        .catch((e) => {
          if (e.name !== "AbortError") {
            setHits([]);
            setError(String(e));
          }
        });
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [term]);

  if (error) {
    return (
      <div className="panel p-6 text-sm text-warn">
        Search unavailable — {error}. Is the API running?
      </div>
    );
  }
  if (hits === null) {
    return <div className="mb-3 text-xs text-faint">Searching all entities for “{term}”…</div>;
  }
  if (hits.length === 0) {
    return (
      <div className="panel p-10 text-center text-sm text-muted">
        No entities named “{term}”.
      </div>
    );
  }
  return (
    <>
      <div className="mb-3 text-xs text-faint">
        {hits.length} match{hits.length === 1 ? "" : "es"} for “{term}” · searched all entities by name
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {hits.map((h) => (
          <Link
            key={h.id}
            href={`/entity/${h.id}`}
            className="panel group flex items-center justify-between gap-3 p-4 transition hover:bg-card-hover hover:border-[#243436]"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-text group-hover:text-white">
                {h.name}
              </div>
              <div className="mt-0.5 truncate text-xs text-muted">
                {titleize(h.category)} · {h.entity_type}
              </div>
            </div>
            {h.state ? (
              <StateChip state={h.state} />
            ) : (
              <span className="shrink-0 text-[11px] text-faint">no momentum yet</span>
            )}
          </Link>
        ))}
      </div>
    </>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:border-accent-dim focus:outline-none"
      aria-label={label}
      style={value !== "all" ? { borderColor: "#1B9C8E" } : undefined}
    >
      <option value="all">{label}: All</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {titleize(o)}
        </option>
      ))}
    </select>
  );
}
