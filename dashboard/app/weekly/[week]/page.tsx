import Link from "next/link";
import { getWeekly } from "@/lib/api";
import { titleize, shortDate } from "@/lib/format";
import type { WeeklyResponse, WeeklyWave } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { VerdictChip } from "@/components/VerdictChip";

export const dynamic = "force-dynamic";

function WaveLine({ w, showOutcome }: { w: WeeklyWave; showOutcome?: boolean }) {
  return (
    <Link
      href={`/waves/${w.id}`}
      className="block border-t border-border bg-card px-4 py-3 transition first:border-t-0 hover:bg-bg/40"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm text-text">
          {w.label ?? <span className="text-muted">wave-{w.id}</span>}
        </span>
        {showOutcome && w.verdict && <VerdictChip verdict={w.verdict} />}
        {!showOutcome && w.best_lead_days !== null && w.best_lead_days > 0 && (
          <span className="tabular text-xs text-positive">{w.best_lead_days}d early</span>
        )}
      </div>
      <div className="mt-0.5 text-xs text-muted">
        <span className="tabular">{w.member_count}</span> independent members
        {w.themes.length > 0 && <> · {w.themes.join(" + ")}</>}
        {showOutcome && w.wave_growth !== null && w.cohort_growth !== null && (
          <>
            {" "}
            · <span className="tabular">×{w.wave_growth.toFixed(1)}</span> vs cohort{" "}
            <span className="tabular">×{w.cohort_growth.toFixed(1)}</span>
          </>
        )}
        {showOutcome && <> · formed {shortDate(w.first_seen)}</>}
      </div>
    </Link>
  );
}

function Section({
  title,
  hint,
  children,
  empty,
}: {
  title: string;
  hint: string;
  children: React.ReactNode;
  empty: boolean;
}) {
  return (
    <section className="mb-6">
      <h2 className="mb-1 text-sm font-medium">
        {title} <span className="font-normal text-faint">— {hint}</span>
      </h2>
      <div className="overflow-hidden rounded-lg border border-border">
        {empty ? (
          <div className="bg-card px-4 py-3 text-sm text-muted">Nothing this week.</div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}

export default async function WeeklyPage({ params }: { params: { week: string } }) {
  let data: WeeklyResponse;
  try {
    data = await getWeekly(params.week);
  } catch (e) {
    return (
      <>
        <TopNav active="/weekly/current" />
        <ApiError error={e} />
      </>
    );
  }

  return (
    <>
      <TopNav active="/weekly/current" />
      <main className="mx-auto max-w-[900px] px-5 py-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Week of {shortDate(data.week)}
            </h1>
            <p className="mt-1 max-w-[70ch] text-sm text-muted">
              What formed, what came due, and where we still can&rsquo;t see. Claims are written the
              week they form and settled later — the record is the product, not this page.
            </p>
          </div>
          {data.available_weeks.length > 1 && (
            <div className="flex flex-wrap gap-1">
              {data.available_weeks.slice(0, 8).map((w) => (
                <Link
                  key={w}
                  href={`/weekly/${w}`}
                  className="rounded-md border border-border bg-card px-2 py-1 text-xs text-muted hover:text-text"
                >
                  {w}
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Three sections, deliberately not merged: a new claim, an old claim coming due, and a
            structural blind spot are three different things to a reader. */}
        <Section
          title="⚡ Formed"
          hint="new convergences — several independent teams, same idea, same window"
          empty={data.formed.length === 0}
        >
          {data.formed.map((w) => (
            <WaveLine key={w.id} w={w} />
          ))}
        </Section>

        <Section
          title="📈 Graded"
          hint="claims made earlier, settled this week against their own cohorts"
          empty={data.graded.length === 0}
        >
          {data.graded.map((w) => (
            <WaveLine key={w.id} w={w} showOutcome />
          ))}
        </Section>

        <Section
          title="🚫 Not scored"
          hint="categories with no line in the exposure map — excluded before scoring, not ranked low"
          empty={Object.keys(data.map_gaps).length === 0}
        >
          <div className="bg-card px-4 py-3">
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.map_gaps).map(([cat, n]) => (
                <span
                  key={cat}
                  className="rounded-md border border-border px-2 py-1 text-xs text-muted"
                >
                  {titleize(cat)} <span className="tabular text-faint">{n}</span>
                </span>
              ))}
            </div>
            <p className="mt-2 max-w-[70ch] text-xs text-faint">
              A category that keeps appearing here week after week is the system asking for the
              exposure map to grow. One week is noise; seven in a row is a gap.
            </p>
          </div>
        </Section>
      </main>
    </>
  );
}
