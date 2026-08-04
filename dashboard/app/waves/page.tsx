import Link from "next/link";
import { getWaves } from "@/lib/api";
import { titleize, shortDate } from "@/lib/format";
import type { WaveSummary } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { VerdictChip } from "@/components/VerdictChip";

export const dynamic = "force-dynamic";

export default async function WavesPage() {
  let waves: WaveSummary[];
  try {
    waves = await getWaves();
  } catch (e) {
    return (
      <>
        <TopNav active="/waves" />
        <ApiError error={e} />
      </>
    );
  }

  return (
    <>
      <TopNav active="/waves" />
      <main className="mx-auto max-w-[1100px] px-5 py-6">
        <div className="mb-5">
          <h1 className="text-xl font-semibold tracking-tight">Waves</h1>
          <p className="mt-1 max-w-[70ch] text-sm text-muted">
            Several <span className="text-text">independent</span> teams starting on the same idea at
            once. Every other view measures how fast one thing moves; this measures how many
            unrelated people moved at the same time. Deterministic — no model decides membership.
          </p>
        </div>

        {waves.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted">
            <p className="text-text">No waves detected yet.</p>
            <p className="mt-2 max-w-[70ch]">
              A wave needs at least four independent entities that appeared inside the same window
              and share a semantic neighbourhood. Detection runs on <code>seismo waves</code>, and
              it reads the semantic graph — if that graph is sparse, waves will be rare rather than
              wrong.
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {waves.map((w) => (
              <Link
                key={w.id}
                href={`/waves/${w.id}`}
                className="group rounded-lg border border-border bg-card p-4 transition hover:border-accent/60"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="truncate text-[15px] font-medium">
                        {w.label ?? (
                          <span className="text-muted">
                            wave-{w.id} <span className="text-faint">(unnamed)</span>
                          </span>
                        )}
                      </h2>
                      {w.verdict && <VerdictChip verdict={w.verdict} />}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                      <span>
                        formed <span className="tabular text-text">{shortDate(w.first_seen)}</span>
                      </span>
                      <span className="text-faint">·</span>
                      <span>
                        <span className="tabular text-text">{w.member_count}</span> independent
                        members
                      </span>
                      {w.categories.length > 0 && (
                        <>
                          <span className="text-faint">·</span>
                          <span>{w.categories.map(titleize).join(", ")}</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-5 text-right">
                    {w.best_lead_days !== null && w.best_lead_days > 0 && (
                      <div>
                        <div className="tabular text-xl font-semibold text-positive">
                          {w.best_lead_days}d
                        </div>
                        <div className="text-[10px] uppercase tracking-wide text-faint">
                          earliest lead
                        </div>
                      </div>
                    )}
                    <div>
                      <div className="tabular text-xl font-semibold">{w.strength.toFixed(2)}</div>
                      <div className="text-[10px] uppercase tracking-wide text-faint">strength</div>
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}

        <p className="mt-6 max-w-[75ch] text-xs text-faint">
          Strength is <span className="tabular">size × evidence breadth × how tight the window is</span>
          . The thresholds behind it are uncalibrated guesses until this has run against real data —
          read member count and the window first, and treat the score as a sort order rather than a
          measurement.
        </p>
      </main>
    </>
  );
}
