import { MATURITY_LADDER, shortDate, titleize } from "@/lib/format";
import type { MaturityRung } from "@/lib/types";

export function MaturityLadder({ reached }: { reached: MaturityRung[] }) {
  const byStage = new Map(reached.map((r) => [r.stage, r.promoted_at]));
  const top = MATURITY_LADDER.reduce((acc, s, i) => (byStage.has(s) ? i : acc), -1);
  return (
    <div className="panel p-4">
      <div className="label mb-3">Maturity Ladder</div>
      <ol className="space-y-2">
        {MATURITY_LADDER.map((stage, i) => {
          const on = i <= top && (byStage.has(stage) || i < top);
          const when = byStage.get(stage);
          return (
            <li key={stage} className="flex items-center gap-3 text-sm">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{
                  background: on ? "#34D399" : "#243436",
                  boxShadow: on ? "0 0 8px #34D399" : undefined,
                }}
              />
              <span className={on ? "text-text" : "text-faint"}>{titleize(stage)}</span>
              {when && (
                <span className="tabular ml-auto text-[11px] text-faint">{shortDate(when)}</span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
