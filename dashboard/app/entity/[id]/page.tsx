import Link from "next/link";
import { getEntity } from "@/lib/api";
import { pct, shortDate, titleize } from "@/lib/format";
import type { EntityDossier } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { StateChip } from "@/components/StateChip";
import { CardPanel } from "@/components/CardPanel";
import { MetricChart } from "@/components/MetricChart";
import { MaturityLadder } from "@/components/MaturityLadder";
import { Kpi, KpiRow } from "@/components/Kpi";
import { ApiError } from "@/components/ApiError";

export const dynamic = "force-dynamic";

export default async function DossierPage({ params }: { params: { id: string } }) {
  let d: EntityDossier;
  try {
    d = await getEntity(Number(params.id));
  } catch (e) {
    return (
      <>
        <TopNav />
        <ApiError error={e} />
      </>
    );
  }

  const headline =
    d.metrics.find((m) => m.metric === "gh_stars") ?? d.metrics.find((m) => m.points.length > 1);

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
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
              <Meta icon="tag" text={titleize(d.category)} />
              <Meta icon="user" text={d.owner ?? "unknown owner"} />
              <Meta icon="clock" text={`first seen ${shortDate(d.first_seen)}`} />
              <Meta icon="layers" text={`tier: ${d.tracking_tier}`} />
              {Object.entries(d.anchors).map(([reg, nid]) => (
                <Meta key={reg} icon="link" text={`${reg}:${nid}`} />
              ))}
            </div>
          </div>
        </header>

        <div className="mt-5">
          <KpiRow>
            <Kpi label="Velocity Percentile" value={pct(d.velocity_pctl)} sub="within cohort" accent="#2DD4BF" />
            <Kpi label="Momentum" value={titleize(d.state)} sub={d.provisional ? "provisional cohort" : "committed"} />
            <Kpi label="Maturity" value={titleize(d.card?.maturity_stage ?? d.maturity.at(-1)?.stage ?? null)} sub={`${d.maturity.length} rungs reached`} />
            <Kpi label="Cohort Size" value={d.cohort_n ?? "—"} sub="peers ranked against" />
          </KpiRow>
        </div>

        <div className="mt-4">
          <CardPanel card={d.card} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_320px]">
          <div className="panel p-4">
            <div className="mb-1 flex items-center justify-between">
              <div className="label">{headline ? titleize(headline.metric) : "Metric Trajectory"}</div>
              <div className="text-[11px] text-faint">promotions ● shown on line</div>
            </div>
            <MetricChart points={headline?.points ?? []} promotions={d.maturity} />
          </div>
          <MaturityLadder reached={d.maturity} />
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

function Meta({ icon, text }: { icon: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon name={icon} />
      {text}
    </span>
  );
}

function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    tag: "M7 7h.01M7 3h5l9 9-5 5-9-9V3z",
    user: "M12 12a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0",
    clock: "M12 8v4l3 2m6-2a9 9 0 11-18 0 9 9 0 0118 0z",
    layers: "M12 3l9 5-9 5-9-5 9-5zm9 9l-9 5-9-5",
    link: "M10 13a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1m-2 6a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1",
  };
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#55686B" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={paths[name] ?? ""} />
    </svg>
  );
}
