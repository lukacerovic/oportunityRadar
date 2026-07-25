import Link from "next/link";
import { getCalibration, getChanges } from "@/lib/api";
import type { CalibrationResponse, ChangeItem, ChangesResponse } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { InfoButton } from "@/components/InfoModal";
import { ChangesGroupedList } from "@/components/ChangesGroupedList";
import { ChangeRow } from "@/components/ChangeRow";
import { HELP } from "@/lib/help";

export const dynamic = "force-dynamic";

// Below this many rows, a flat list reads fine — grouping/filtering only earns its keep once a
// kind's row count starts to overwhelm (some days: 300+ maturity promotions in one section).
const GROUP_THRESHOLD = 15;

// Each Changes group: label + accent (doc 09 §1). Deterministic, no LLM — boring on purpose.
const GROUP: Record<string, { label: string; color: string }> = {
  gate_week: { label: "Gate — week rollup", color: "#2DD4BF" },
  brief_published: { label: "Briefs published", color: "#34D399" },
  brief_drafted: { label: "Briefs drafted", color: "#38BDF8" },
  state_up: { label: "Momentum ↑", color: "#34D399" },
  state_down: { label: "Momentum ↓", color: "#F59E0B" },
  promotion: { label: "Maturity promotions", color: "#A78BFA" },
  new_entity: { label: "New — survived the 7-day gate", color: "#94A3B8" },
};

export default async function ChangesPage({ params }: { params: { day: string } }) {
  let data: ChangesResponse;
  let cal: CalibrationResponse | null = null;
  try {
    data = await getChanges(params.day);
    cal = await getCalibration().catch(() => null);
  } catch (e) {
    return (
      <>
        <TopNav active="/changes/latest" />
        <ApiError error={e} />
      </>
    );
  }

  return (
    <>
      <TopNav active="/changes/latest" />
      <main className="mx-auto max-w-[1000px] px-5 py-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">Changes</h1>
              <InfoButton content={HELP.changes} />
            </div>
            <p className="mt-1 text-sm text-muted">
              What moved on{" "}
              <span className="tabular text-faint">{data.day}</span> — momentum shifts, promotions,
              and the brief lifecycle. Deterministic diffs, no narrative model (doc 09).
            </p>
          </div>
          <div className="tabular text-sm text-muted">{data.total} change(s)</div>
        </div>

        {/* day switcher */}
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <span className="text-xs text-faint">day</span>
          {data.available_days.length === 0 && (
            <span className="tabular text-sm text-muted">{data.day}</span>
          )}
          {data.available_days.map((d) => {
            const on = d === data.day;
            return (
              <Link
                key={d}
                href={`/changes/${d}`}
                className="tabular rounded-full border px-3 py-1 text-xs transition"
                style={
                  on
                    ? { background: "#2DD4BF", borderColor: "#2DD4BF", color: "#0A0F0F" }
                    : { borderColor: "#1E2A2C" }
                }
              >
                {d.slice(5)}
              </Link>
            );
          })}
        </div>

        {cal && Object.keys(cal.latest).length > 0 && <CalibrationStrip cal={cal} />}

        {data.total === 0 && (
          <div className="panel p-10 text-center text-sm text-muted">
            Nothing computed for this day. Run{" "}
            <code className="text-accent">seismo changes</code> after the daily heartbeat to populate
            it.
          </div>
        )}

        {Object.entries(data.groups).map(([kind, items]) => {
          const g = GROUP[kind] ?? { label: kind, color: "#64748B" };
          return (
            <section key={kind} className="mb-5">
              <div className="mb-2 flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: g.color, boxShadow: `0 0 8px ${g.color}` }}
                />
                <h2 className="text-sm font-semibold">{g.label}</h2>
                <span className="tabular text-xs text-faint">{items.length}</span>
              </div>
              {items.length > GROUP_THRESHOLD ? (
                <ChangesGroupedList items={items} itemLabel={g.label.toLowerCase()} />
              ) : (
                <div className="space-y-1.5">
                  {items.map((it, i) => (
                    <ChangeRow key={i} item={it} />
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </main>
    </>
  );
}

function CalibrationStrip({ cal }: { cal: CalibrationResponse }) {
  const META: Record<string, { label: string; hint: string; good: "high" | "low" }> = {
    breakout_survival: {
      label: "Breakout survival",
      hint: "share of ≥90d-old breakout calls still alive — healthy ≥50%",
      good: "high",
    },
    fade_reaccel: {
      label: "Fade false-alarm",
      hint: "share of fade calls that re-accelerated within 60d — lower is better",
      good: "low",
    },
  };
  return (
    <div className="panel mb-6 flex flex-wrap gap-6 p-5">
      <div className="text-[11px] uppercase tracking-wide text-faint">Calibration</div>
      {Object.entries(cal.latest).map(([metric, pt]) => {
        const meta = META[metric] ?? { label: metric, hint: "", good: "high" as const };
        const pctv = pt.value === null ? null : Math.round(pt.value * 100);
        const color =
          pctv === null
            ? "#64748B"
            : (meta.good === "high" ? pctv >= 50 : pctv <= 50)
              ? "#34D399"
              : "#F59E0B";
        return (
          <div key={metric} title={meta.hint}>
            <div className="tabular text-xl font-semibold" style={{ color }}>
              {pctv === null ? "—" : `${pctv}%`}
            </div>
            <div className="text-[11px] text-muted">
              {meta.label} <span className="text-faint">· n={pt.sample_n}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
