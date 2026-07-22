import Link from "next/link";
import { pct } from "@/lib/format";
import { STATE_META } from "@/lib/format";
import type { RadarEntity } from "@/lib/types";

// "Something is taking big motion" — the entities with real upward momentum right now, surfaced
// at the top so you don't have to go hunting. Draws from the loaded, momentum-ranked set.
export function MoversStrip({ entities }: { entities: RadarEntity[] }) {
  const movers = entities
    .filter((e) => e.state === "breakout" || e.state === "accelerating")
    .slice(0, 6);
  if (movers.length === 0) return null;

  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-text">🔥 Taking off</span>
        <span className="text-xs text-faint">biggest movers right now</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {movers.map((e) => {
          const meta = STATE_META[e.state];
          return (
            <Link
              key={e.id}
              href={`/entity/${e.id}`}
              className="panel group relative overflow-hidden p-3 transition hover:bg-card-hover"
            >
              <span
                className="absolute inset-x-0 top-0 h-[3px]"
                style={{ background: meta.color }}
              />
              <div className="truncate text-[13px] font-semibold text-text group-hover:text-white">
                {e.name}
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px]">
                <span style={{ color: meta.color }}>{meta.label}</span>
                <span className="tabular text-muted">{pct(e.velocity_pctl)}</span>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
