import Link from "next/link";
import { getEntity, getBriefSafe } from "@/lib/api";
import { compactNum, pct, shortDate, titleize } from "@/lib/format";
import type { Brief, EntityDossier, MetricSeries } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { StateChip } from "@/components/StateChip";
import { CardPanel } from "@/components/CardPanel";
import { MetricChart } from "@/components/MetricChart";
import { MaturityLadder } from "@/components/MaturityLadder";
import { EvidenceList } from "@/components/EvidenceList";
import { MarketImpact } from "@/components/MarketImpact";
import { RelatedEntities } from "@/components/RelatedEntities";
import { MomentumTimeline } from "@/components/MomentumTimeline";
import { Kpi, KpiRow } from "@/components/Kpi";
import { ApiError } from "@/components/ApiError";
import { InfoButton } from "@/components/InfoModal";
import { HELP } from "@/lib/help";

export const dynamic = "force-dynamic";

// Which metric best represents "popularity / attention over time", most-preferred first.
const ATTENTION: { metric: string; label: string }[] = [
  { metric: "or_tokens_wk", label: "OpenRouter Tokens (wk)" },
  { metric: "hf_downloads_30d", label: "Downloads (30d)" },
  { metric: "gh_stars", label: "GitHub Stars" },
  { metric: "hn_points_7d", label: "Hacker News Points (7d)" },
  { metric: "pypi_downloads_7d", label: "PyPI Downloads (7d)" },
  { metric: "evidence_breadth", label: "Evidence Breadth" },
];

function pickAttention(metrics: MetricSeries[]): { series: MetricSeries; label: string } | null {
  for (const a of ATTENTION) {
    const s = metrics.find((m) => m.metric === a.metric && m.points.length >= 2);
    if (s) return { series: s, label: a.label };
  }
  const longest = [...metrics].filter((m) => m.points.length >= 2).sort((a, b) => b.points.length - a.points.length)[0];
  return longest ? { series: longest, label: titleize(longest.metric) } : null;
}

export default async function DossierPage({ params }: { params: { id: string } }) {
  const id = Number(params.id);
  let d: EntityDossier;
  try {
    d = await getEntity(id);
  } catch (e) {
    return (
      <>
        <TopNav />
        <ApiError error={e} />
      </>
    );
  }
  const brief: Brief | null = await getBriefSafe(id);

  const attention = pickAttention(d.metrics ?? []);
  const latestAttention = attention?.series.points.at(-1)?.value;

  return (
    <>
      <TopNav />
      <main className="mx-auto max-w-[1200px] px-5 py-6">
        <Link href="/" className="text-xs text-muted hover:text-text">
          ← Radar
        </Link>

        <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">{d.name}</h1>
              <StateChip state={d.state} provisional={d.provisional} size="md" />
              <InfoButton content={HELP.entity} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
              <span>{titleize(d.category)}</span>
              <span>·</span>
              <span>{d.entity_type}</span>
              <span>·</span>
              <span>{d.owner ?? "unknown owner"}</span>
              <span>·</span>
              <span>first seen {shortDate(d.first_seen)}</span>
            </div>
            {(d.themes ?? []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(d.themes ?? []).map((t) => (
                  <span key={t} className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted">
                    {titleize(t)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </header>

        <div className="mt-5">
          <KpiRow>
            <Kpi label="Velocity Percentile" value={pct(d.velocity_pctl)} sub="vs. its cohort" accent="#2DD4BF" />
            <Kpi label="Momentum" value={titleize(d.state)} sub={d.provisional ? "provisional cohort" : "committed"} />
            <Kpi
              label={attention ? attention.label : "Attention"}
              value={latestAttention != null ? compactNum(latestAttention) : "—"}
              sub="latest observed"
            />
            <Kpi label="Maturity" value={titleize(d.card?.maturity_stage ?? d.maturity.at(-1)?.stage ?? null)} sub={`${d.maturity.length} rungs reached`} />
          </KpiRow>
        </div>

        {/* Two columns: readable content + sources on the left, signals on the right. */}
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_360px]">
          <div className="space-y-4">
            <CardPanel card={d.card} />

            {d.description && (
              <div className="panel p-4">
                <div className="label mb-2">What we collected</div>
                <p className="whitespace-pre-line text-[13px] leading-relaxed text-muted">
                  {d.description}
                </p>
              </div>
            )}

            <section>
              <div className="mb-2 flex items-center gap-2">
                <h2 className="text-sm font-semibold text-text">Sources</h2>
                <span className="text-xs text-faint">{(d.evidence ?? []).length}</span>
              </div>
              <EvidenceList items={d.evidence ?? []} />
            </section>
          </div>

          <div className="space-y-4">
            <div className="panel p-4">
              <div className="mb-1 flex items-center justify-between">
                <div className="label">{attention ? `Popularity · ${attention.label}` : "Popularity"}</div>
                <div className="text-[11px] text-faint">promotions ● on line</div>
              </div>
              {attention ? (
                <MetricChart points={attention.series.points} promotions={d.maturity} height={200} />
              ) : (
                <div className="flex h-40 items-center justify-center text-center text-xs text-faint">
                  No attention history yet — needs repeated tracking over several days to plot a trend.
                </div>
              )}
            </div>

            <MomentumTimeline history={d.momentum_history ?? []} />

            <MarketImpact brief={brief} entityId={id} />

            <RelatedEntities items={d.related ?? []} />

            <MaturityLadder reached={d.maturity} />
          </div>
        </div>

        {d.card_versions.length > 1 && (
          <p className="mt-3 text-xs text-faint">
            {d.card_versions.length} card versions on record — comprehension drift is itself a signal
            (a project whose function changes is pivoting).
          </p>
        )}
      </main>
    </>
  );
}
