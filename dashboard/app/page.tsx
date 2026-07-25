import Link from "next/link";
import { getRadar } from "@/lib/api";
import { STATE_META } from "@/lib/format";
import type { MomentumState, RadarResponse } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { RadarGrid } from "@/components/RadarGrid";
import { MoversStrip } from "@/components/MoversStrip";
import { ApiError } from "@/components/ApiError";
import { InfoButton } from "@/components/InfoModal";
import { HELP } from "@/lib/help";

export const dynamic = "force-dynamic";

const FILTERS: (MomentumState | "all")[] = [
  "all",
  "breakout",
  "accelerating",
  "simmering",
  "fading",
  "dormant",
];

// Collection sources map raw `raw_events.source` values → display labels.
const SOURCES: { key: string; label: string }[] = [
  { key: "github", label: "GitHub" },
  { key: "hn", label: "Hacker News" },
  { key: "arxiv", label: "arXiv" },
  { key: "hf", label: "Hugging Face" },
];

export default async function RadarPage({
  searchParams,
}: {
  searchParams: { state?: string; source?: string; gated?: string };
}) {
  const active = (searchParams.state as MomentumState | undefined) ?? "all";
  const activeSource = searchParams.source ?? "all";
  const activeGated = searchParams.gated === "true";

  // Build a URL that changes one filter while preserving the others (state ↔ source ↔ gated).
  const hrefWith = (next: { state?: string; source?: string; gated?: boolean }) => {
    const state = next.state ?? (active === "all" ? undefined : active);
    const src = next.source ?? (activeSource === "all" ? undefined : activeSource);
    const gated = next.gated ?? activeGated;
    const q = new URLSearchParams();
    if (state && state !== "all") q.set("state", state);
    if (src && src !== "all") q.set("source", src);
    if (gated) q.set("gated", "true");
    const s = q.toString();
    return s ? `/?${s}` : "/";
  };

  let data: RadarResponse;
  try {
    data = await getRadar({
      state: active === "all" ? undefined : active,
      source: activeSource === "all" ? undefined : activeSource,
      gated: activeGated,
      limit: 240,
    });
  } catch (e) {
    return (
      <>
        <TopNav active="/" />
        <ApiError error={e} />
      </>
    );
  }

  const counts = data.entities.reduce<Record<string, number>>((acc, e) => {
    acc[e.state] = (acc[e.state] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <TopNav active="/" />
      <main className="mx-auto max-w-[1400px] px-5 py-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">Radar</h1>
              <InfoButton content={HELP.radar} />
            </div>
            <p className="mt-1 text-sm text-muted">
              {data.count} tracked entities · ranked by momentum, then velocity ·{" "}
              <span className="tabular text-faint">
                as of {new Date(data.as_of).toISOString().slice(0, 10)}
              </span>
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {FILTERS.map((f) => {
              const on = f === active;
              const color = f === "all" ? "#2DD4BF" : STATE_META[f].color;
              return (
                <Link
                  key={f}
                  href={hrefWith({ state: f })}
                  className={`rounded-full border px-3 py-1 text-xs capitalize transition ${
                    on ? "text-bg" : "text-muted hover:text-text"
                  }`}
                  style={
                    on
                      ? { background: color, borderColor: color }
                      : { borderColor: "#1E2A2C" }
                  }
                >
                  {f}
                  {f !== "all" && counts[f] ? (
                    <span className="ml-1.5 opacity-70">{counts[f]}</span>
                  ) : null}
                </Link>
              );
            })}
            <span className="mx-1 h-4 w-px bg-border" />
            <Link
              href={hrefWith({ gated: !activeGated })}
              title="Only entities that have ever passed the weekly significance gate — queued for or already given a brief."
              className={`rounded-full border px-3 py-1 text-xs transition ${
                activeGated ? "text-bg" : "text-muted hover:text-text"
              }`}
              style={
                activeGated
                  ? { background: "#A78BFA", borderColor: "#A78BFA" }
                  : { borderColor: "#1E2A2C" }
              }
            >
              📋 Gated
              {data.gated_count != null ? (
                <span className="ml-1.5 opacity-70">{data.gated_count}</span>
              ) : null}
            </Link>
          </div>
        </div>

        {active === "all" && activeSource === "all" && !activeGated && (
          <MoversStrip entities={data.entities} />
        )}

        <div className="mb-5 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs text-faint">Source</span>
          <Link
            href={hrefWith({ source: "all" })}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              activeSource === "all"
                ? "border-accent-dim text-text"
                : "border-border text-muted hover:text-text"
            }`}
            style={activeSource === "all" ? { background: "#12211F" } : undefined}
          >
            All
          </Link>
          {SOURCES.map((s) => {
            const on = s.key === activeSource;
            const count = data.source_counts?.[s.key] ?? 0;
            return (
              <Link
                key={s.key}
                href={hrefWith({ source: on ? "all" : s.key })}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  on
                    ? "border-accent-dim text-text"
                    : `border-border hover:text-text ${count === 0 ? "text-faint" : "text-muted"}`
                }`}
                style={on ? { background: "#12211F" } : undefined}
              >
                {s.label}
                <span className="ml-1.5 opacity-70">{count}</span>
              </Link>
            );
          })}
        </div>

        {data.entities.length === 0 ? (
          <div className="panel p-10 text-center text-sm text-muted">
            {activeSource === "all" ? (
              <>
                No entities in this state yet. Momentum lights up once the daily heartbeat
                accumulates snapshots — until then most entities read{" "}
                <span className="text-dormant">dormant</span>.
              </>
            ) : (
              <>No entities from this source{active !== "all" ? " in this momentum state" : ""}.</>
            )}
          </div>
        ) : (
          <RadarGrid entities={data.entities} />
        )}
      </main>
    </>
  );
}
