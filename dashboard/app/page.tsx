import Link from "next/link";
import { getRadar } from "@/lib/api";
import { STATE_META } from "@/lib/format";
import type { MomentumState, RadarResponse } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { EntityCard } from "@/components/EntityCard";
import { ApiError } from "@/components/ApiError";

export const dynamic = "force-dynamic";

const FILTERS: (MomentumState | "all")[] = [
  "all",
  "breakout",
  "accelerating",
  "simmering",
  "fading",
  "dormant",
];

export default async function RadarPage({
  searchParams,
}: {
  searchParams: { state?: string };
}) {
  const active = (searchParams.state as MomentumState | undefined) ?? "all";
  let data: RadarResponse;
  try {
    data = await getRadar({ state: active === "all" ? undefined : active, limit: 240 });
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
            <h1 className="text-xl font-semibold tracking-tight">Radar</h1>
            <p className="mt-1 text-sm text-muted">
              {data.count} tracked entities · ranked by momentum, then velocity ·{" "}
              <span className="tabular text-faint">
                as of {new Date(data.as_of).toISOString().slice(0, 10)}
              </span>
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map((f) => {
              const on = f === active;
              const color = f === "all" ? "#2DD4BF" : STATE_META[f].color;
              return (
                <Link
                  key={f}
                  href={f === "all" ? "/" : `/?state=${f}`}
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
          </div>
        </div>

        {data.entities.length === 0 ? (
          <div className="panel p-10 text-center text-sm text-muted">
            No entities in this state yet. Momentum lights up once the daily heartbeat accumulates
            snapshots — until then most entities read <span className="text-dormant">dormant</span>.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {data.entities.map((e) => (
              <EntityCard key={e.id} e={e} />
            ))}
          </div>
        )}
      </main>
    </>
  );
}
