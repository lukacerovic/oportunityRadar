import Link from "next/link";
import { getWave } from "@/lib/api";
import { titleize, shortDate } from "@/lib/format";
import type { WaveDetail } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { VerdictChip } from "@/components/VerdictChip";

export const dynamic = "force-dynamic";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint} className="rounded-lg border border-border bg-card px-3 py-2">
      <div className="tabular text-lg font-semibold">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}

export default async function WaveDetailPage({ params }: { params: { id: string } }) {
  let wave: WaveDetail;
  try {
    wave = await getWave(params.id);
  } catch (e) {
    return (
      <>
        <TopNav active="/waves" />
        <ApiError error={e} />
      </>
    );
  }

  const earliest = wave.observations.filter((o) => o.lead_days > 0)[0] ?? null;
  const graded = wave.outcomes.filter((o) => o.verdict !== "unmeasurable");

  return (
    <>
      <TopNav active="/waves" />
      <main className="mx-auto max-w-[1100px] px-5 py-6">
        <Link href="/waves" className="text-xs text-muted hover:text-text">
          ← all waves
        </Link>

        <div className="mt-2 mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              {wave.label ?? (
                <span className="text-muted">
                  wave-{wave.id} <span className="text-faint">(unnamed)</span>
                </span>
              )}
            </h1>
            <p className="mt-1 text-sm text-muted">
              {wave.members.length} independent members appeared within{" "}
              <span className="tabular text-text">{wave.components.span_days ?? "?"} days</span> ·{" "}
              {(wave.components.categories ?? []).map(titleize).join(", ") || "uncategorized"}
            </p>
          </div>
          <div className="flex gap-2">
            <Stat
              label="strength"
              value={wave.strength.toFixed(2)}
              hint="size × evidence breadth × window tightness — a sort order, not a measurement"
            />
            {earliest && (
              <Stat
                label="earliest lead"
                value={`${earliest.lead_days}d`}
                hint="Days between the earliest authored mention we hold and the day this wave formed"
              />
            )}
          </div>
        </div>

        {/* The timeline is the whole product: someone said it, then it formed, then it was graded. */}
        <section className="mb-6 rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-medium">Timeline</h2>
          <ol className="relative ml-2 border-l border-border pl-5 text-sm">
            {earliest && (
              <li className="relative pb-4">
                <span className="absolute -left-[27px] top-1.5 h-2 w-2 rounded-full bg-positive" />
                <div className="tabular text-xs text-muted">{shortDate(earliest.observed_at)}</div>
                <div className="mt-0.5">
                  <span className="text-text">{earliest.author_handle ?? "unknown"}</span>{" "}
                  <span className="text-muted">mentioned it on {earliest.source}</span>{" "}
                  <span className="text-positive">— {earliest.lead_days} days early</span>
                </div>
                {earliest.excerpt && (
                  <p className="mt-1 max-w-[75ch] text-xs italic text-faint">
                    &ldquo;{earliest.excerpt}&rdquo;
                  </p>
                )}
              </li>
            )}
            <li className="relative pb-4">
              <span className="absolute -left-[27px] top-1.5 h-2 w-2 rounded-full bg-accent" />
              <div className="tabular text-xs text-muted">{shortDate(wave.first_seen)}</div>
              <div className="mt-0.5 text-text">
                Wave formed — {wave.members.length} independent members
              </div>
            </li>
            <li className="relative">
              <span className="absolute -left-[27px] top-1.5 h-2 w-2 rounded-full bg-border" />
              <div className="tabular text-xs text-muted">
                {wave.outcomes[0] ? `+${wave.outcomes[0].horizon_days} days` : "horizon pending"}
              </div>
              <div className="mt-0.5 text-muted">
                {graded.length > 0 ? (
                  <>
                    Outcome:{" "}
                    {graded.map((o) => (
                      <span key={o.metric} className="mr-2">
                        <VerdictChip verdict={o.verdict} />
                      </span>
                    ))}
                  </>
                ) : (
                  "Not yet gradeable — the horizon hasn't elapsed, or no usage metric covers these members."
                )}
              </div>
            </li>
          </ol>
        </section>

        {/* Members deliberately do NOT render as a node-link graph: in the known case no member
            pointed at any other, so a graph would be N disconnected dots saying nothing. What
            explains the grouping is the shared neighbour, so that is what each row leads with. */}
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-medium">
            Members{" "}
            <span className="font-normal text-faint">
              — linked by shared neighbourhood, not by edges between them
            </span>
          </h2>
          <div className="overflow-hidden rounded-lg border border-border">
            {wave.members.map((mem, i) => {
              const shared = [
                ...(mem.link_reason.shared_neighbours ?? []),
                ...(mem.link_reason.shared_neighbour_categories ?? []),
              ];
              return (
                <div
                  key={mem.entity_id}
                  className={`flex flex-wrap items-center justify-between gap-3 bg-card px-4 py-2.5 ${
                    i > 0 ? "border-t border-border" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <Link
                      href={`/entity/${mem.entity_id}`}
                      className="text-sm text-text hover:text-accent"
                    >
                      {mem.name}
                    </Link>
                    <div className="mt-0.5 text-xs text-muted">
                      joined <span className="tabular">{shortDate(mem.joined_at)}</span>
                      {mem.category && <> · {titleize(mem.category)}</>}
                    </div>
                  </div>
                  <div className="max-w-[52ch] text-right text-xs">
                    {shared.length > 0 ? (
                      <span className="text-faint">
                        via <span className="text-muted">{shared.slice(0, 3).join(", ")}</span>
                      </span>
                    ) : (
                      <span className="text-faint">no recorded link reason</span>
                    )}
                    {mem.independence.conflicts?.length > 0 && (
                      <div
                        className="mt-0.5 text-negative"
                        title={mem.independence.conflicts.map((c) => c.detail).join("; ")}
                      >
                        {mem.independence.conflicts.map((c) => c.kind).join(", ")}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {(wave.components.collapsed ?? 0) > 0 && (
            <p className="mt-2 text-xs text-faint">
              {wave.components.collapsed} further member(s) were collapsed as non-independent —
              same team, shared owner, or a dependency between them. They are recorded, not counted.
            </p>
          )}
        </section>

        <section className="mb-6">
          <h2 className="mb-2 text-sm font-medium">
            Early mentions{" "}
            <span className="font-normal text-faint">— authored, timestamped, source time only</span>
          </h2>
          {wave.observations.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted">
              None found. Only sources carrying both an author and a real publication time are
              searched — currently Hacker News stories. The community layer is built but has never
              been run, and the Substack collector is approved but unbuilt; both would land here.
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              {wave.observations.map((o, i) => (
                <div
                  key={`${o.source}-${o.observed_at}-${i}`}
                  className={`bg-card px-4 py-2.5 ${i > 0 ? "border-t border-border" : ""}`}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm text-text">{o.author_handle ?? "unknown"}</span>
                    <span
                      className={`tabular text-xs ${o.lead_days > 0 ? "text-positive" : "text-faint"}`}
                    >
                      {o.lead_days > 0 ? `${o.lead_days}d early` : `${-o.lead_days}d after`}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {o.source} · <span className="tabular">{shortDate(o.observed_at)}</span>
                    {o.entity_name && <> · on {o.entity_name}</>}
                  </div>
                  {o.excerpt && (
                    <p className="mt-1 max-w-[80ch] text-xs italic text-faint">{o.excerpt}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-2 text-sm font-medium">
            Outcome{" "}
            <span className="font-normal text-faint">
              — measured against the members&rsquo; own cohorts, never in absolute terms
            </span>
          </h2>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="bg-bg text-left text-[11px] uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-4 py-2 font-medium">Metric</th>
                  <th className="px-4 py-2 font-medium">Wave</th>
                  <th className="px-4 py-2 font-medium">Cohort</th>
                  <th className="px-4 py-2 font-medium">Percentile</th>
                  <th className="px-4 py-2 font-medium">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {wave.outcomes.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="bg-card px-4 py-3 text-muted">
                      Not evaluated yet — run <code>seismo waves</code> after the horizon elapses.
                    </td>
                  </tr>
                ) : (
                  wave.outcomes.map((o) => (
                    <tr key={o.metric} className="border-t border-border bg-card">
                      <td className="px-4 py-2 text-muted">{o.metric}</td>
                      <td className="tabular px-4 py-2">
                        {o.wave_growth === null ? "—" : `×${o.wave_growth.toFixed(1)}`}
                      </td>
                      <td className="tabular px-4 py-2 text-muted">
                        {o.cohort_growth === null ? "—" : `×${o.cohort_growth.toFixed(1)}`}
                      </td>
                      <td className="tabular px-4 py-2">
                        {o.percentile === null ? "—" : o.percentile.toFixed(2)}
                      </td>
                      <td className="px-4 py-2">
                        <VerdictChip verdict={o.verdict} />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </>
  );
}
