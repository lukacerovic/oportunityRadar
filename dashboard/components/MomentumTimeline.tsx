import { STATE_META, shortDate } from "@/lib/format";
import type { MomentumPoint } from "@/lib/types";

// How the momentum state moved over time — a compact colored strip, one segment per day, plus the
// labeled transitions. The "did this take off, and when?" story the single metric chart can't tell.
export function MomentumTimeline({ history }: { history: MomentumPoint[] }) {
  if (history.length === 0) {
    return (
      <div className="panel p-4">
        <div className="label mb-1">Momentum history</div>
        <div className="text-xs text-faint">No momentum recorded yet.</div>
      </div>
    );
  }
  // Transitions = points where the state changed from the previous day.
  const transitions = history.filter((p, i) => i === 0 || p.state !== history[i - 1].state);
  return (
    <div className="panel p-4">
      <div className="label mb-2">Momentum history</div>
      <div className="flex h-3 overflow-hidden rounded-full">
        {history.map((p, i) => (
          <div
            key={i}
            className="flex-1"
            style={{ background: STATE_META[p.state]?.color ?? "#334155" }}
            title={`${shortDate(p.day)} · ${STATE_META[p.state]?.label ?? p.state}`}
          />
        ))}
      </div>
      <div className="mt-3 space-y-1">
        {transitions.slice(-5).map((p, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATE_META[p.state]?.color }} />
              <span style={{ color: STATE_META[p.state]?.color }}>{STATE_META[p.state]?.label ?? p.state}</span>
            </span>
            <span className="tabular text-faint">{shortDate(p.day)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
