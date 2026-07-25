import Link from "next/link";
import { STATE_META, pct, titleize } from "@/lib/format";
import type { RadarEntity } from "@/lib/types";
import { Sparkline } from "./Sparkline";
import { StateChip } from "./StateChip";

export function EntityCard({ e }: { e: RadarEntity }) {
  const meta = STATE_META[e.state];
  return (
    <Link
      href={`/entity/${e.id}`}
      className="panel group relative flex flex-col gap-3 p-4 transition hover:bg-card-hover hover:border-[#243436]"
    >
      <span
        className="absolute inset-y-0 left-0 w-[3px] rounded-l-xl opacity-70"
        style={{ background: meta.color }}
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[15px] font-semibold text-text group-hover:text-white">
              {e.name}
            </span>
            {e.gated && (
              <span
                title="Has passed the weekly significance gate — queued for or already given a brief."
                className="shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-medium"
                style={{ color: "#A78BFA", background: "#A78BFA1F" }}
              >
                📋
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-xs text-muted">
            {titleize(e.category)} · {e.entity_type}
          </div>
        </div>
        <StateChip state={e.state} provisional={e.provisional} />
      </div>

      <p className="line-clamp-2 min-h-[32px] text-[13px] leading-snug text-muted">
        {e.one_liner ?? <span className="text-faint">No comprehension card yet.</span>}
      </p>

      <div className="mt-auto flex items-end justify-between">
        <div className="flex gap-4 text-xs">
          <div>
            <div className="label">Velocity</div>
            <div className="tabular font-medium text-text">{pct(e.velocity_pctl)}</div>
          </div>
          <div>
            <div className="label">Stage</div>
            <div className="font-medium text-text">{titleize(e.maturity_stage)}</div>
          </div>
        </div>
        <Sparkline data={e.sparkline} color={meta.color} />
      </div>
    </Link>
  );
}
