import Link from "next/link";
import { getGate } from "@/lib/api";
import { titleize } from "@/lib/format";
import type { GateWeekResponse } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { InfoButton } from "@/components/InfoModal";
import { GateSuppressedList } from "@/components/GateSuppressedList";
import { GateRow } from "@/components/GateRow";
import { HELP } from "@/lib/help";

export const dynamic = "force-dynamic";

const GROUP_THRESHOLD = 15;

export default async function GatePage({ params }: { params: { week: string } }) {
  let data: GateWeekResponse;
  try {
    data = await getGate(params.week);
  } catch (e) {
    return (
      <>
        <TopNav active="/gate/current" />
        <ApiError error={e} />
      </>
    );
  }

  const nothing = data.passed.length === 0 && data.suppressed.length === 0;

  return (
    <>
      <TopNav active="/gate/current" />
      <main className="mx-auto max-w-[1100px] px-5 py-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">Significance Gate</h1>
              <InfoButton content={HELP.gate} />
            </div>
            <p className="mt-1 text-sm text-muted">
              Deterministic pick of the week&rsquo;s briefs — no LLM. Score ={" "}
              <span className="tabular text-faint">M × (0.4 + 0.6·R) × (0.4 + 0.6·N)</span>.
            </p>
          </div>
          <div className="text-right">
            <div className="tabular text-2xl font-semibold">
              {data.passed.length}
              <span className="text-faint">/{data.briefs_budget}</span>
            </div>
            <div className="text-[11px] uppercase tracking-wide text-faint">briefs this week</div>
          </div>
        </div>

        {/* week switcher */}
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <span className="text-xs text-faint">week</span>
          {data.available_weeks.length === 0 && (
            <span className="tabular text-sm text-muted">{isoWeek(data.week)}</span>
          )}
          {data.available_weeks.map((w) => {
            const on = w === isoWeek(data.week);
            return (
              <Link
                key={w}
                href={`/gate/${w}`}
                className={`tabular rounded-full border px-3 py-1 text-xs transition ${
                  on ? "text-bg" : "text-muted hover:text-text"
                }`}
                style={on ? { background: "#2DD4BF", borderColor: "#2DD4BF" } : { borderColor: "#1E2A2C" }}
              >
                {w}
              </Link>
            );
          })}
        </div>

        {nothing && (
          <div className="panel p-10 text-center text-sm text-muted">
            No candidates this week. An entity only reaches the gate by hitting{" "}
            <span className="text-accent">accelerating</span> or{" "}
            <span className="text-accent">breakout</span> momentum — until the daily heartbeat builds
            velocity, most stay <span className="text-dormant">dormant</span> and nothing qualifies.
          </div>
        )}

        {data.passed.length > 0 && (
          <Section
            title="Passed — brief queued"
            count={data.passed.length}
            color="#34D399"
            desc="These earned a slot this week. Impact briefs (Stage 7) are generated from here."
          >
            {data.passed.map((d) => (
              <GateRow key={d.entity_id} d={d} tone="pass" />
            ))}
          </Section>
        )}

        {data.suppressed.length > 0 && (
          <Section
            title="Suppressed"
            count={data.suppressed.length}
            color="#64748B"
            desc="Considered but not briefed. Trust in the gate comes from seeing what it withheld — and why."
          >
            {data.suppressed.length > GROUP_THRESHOLD ? (
              <GateSuppressedList items={data.suppressed} />
            ) : (
              data.suppressed.map((d) => <GateRow key={d.entity_id} d={d} tone="suppressed" />)
            )}
          </Section>
        )}

        {Object.keys(data.map_gaps).length > 0 && (
          <div className="panel mt-6 p-5">
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: "#F59E0B" }} />
              <h2 className="text-sm font-semibold">Map gaps</h2>
            </div>
            <p className="mt-1 text-xs text-muted">
              Categories with rising entities but no exposure-map coverage — the prioritized worklist
              for growing the map (doc 07 §2).
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(data.map_gaps).map(([cat, n]) => (
                <span
                  key={cat}
                  className="rounded-md border border-border bg-surface px-2.5 py-1 text-xs"
                >
                  {titleize(cat)} <span className="tabular text-warn">×{n}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function Section({
  title,
  count,
  color,
  desc,
  children,
}: {
  title: string;
  count: number;
  color: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-6">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="tabular text-xs text-faint">{count}</span>
      </div>
      <p className="mb-3 text-xs text-muted">{desc}</p>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function isoWeek(d: string): string {
  // d is an ISO date (YYYY-MM-DD) for the week's Monday; format to YYYY-Www to match available_weeks.
  const dt = new Date(`${d}T00:00:00Z`);
  const target = new Date(dt);
  const day = (dt.getUTCDay() + 6) % 7; // Mon=0
  target.setUTCDate(dt.getUTCDate() - day + 3); // Thursday of this week
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const week =
    1 +
    Math.round(
      ((target.getTime() - firstThursday.getTime()) / 86400000 -
        3 +
        ((firstThursday.getUTCDay() + 6) % 7)) /
        7,
    );
  return `${target.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}
