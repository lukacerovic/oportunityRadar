import Link from "next/link";
import { getBrief } from "@/lib/api";
import { titleize } from "@/lib/format";
import type { Brief, BriefExposure } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { BriefActions } from "@/components/BriefActions";

export const dynamic = "force-dynamic";

const DIRECTION: Record<string, string> = {
  negative: "#F87171",
  positive: "#34D399",
  ambiguous: "#F59E0B",
};

const STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: "Draft — needs review", color: "#38BDF8" },
  published: { label: "Published", color: "#34D399" },
  rejected: { label: "Rejected", color: "#F59E0B" },
  failed: { label: "Failed validation", color: "#F87171" },
  pending: { label: "Pending (budget)", color: "#64748B" },
};

export default async function BriefPage({ params }: { params: { id: string } }) {
  let brief: Brief;
  try {
    brief = await getBrief(Number(params.id));
  } catch (e) {
    return (
      <>
        <TopNav active="/brief" />
        <ApiError error={e} />
      </>
    );
  }

  const s = STATUS[brief.status] ?? { label: brief.status, color: "#64748B" };

  return (
    <>
      <TopNav active="/brief" />
      <main className="mx-auto max-w-[900px] px-5 py-6">
        <Link href="/brief" className="text-xs text-muted hover:text-text">
          ← all briefs
        </Link>

        <div className="mt-2 mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">
                <Link href={`/entity/${brief.entity_id}`} className="hover:text-accent">
                  {brief.entity_name}
                </Link>
              </h1>
              <span className="tabular text-[11px] text-faint">v{brief.version}</span>
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                style={{ color: s.color, background: `${s.color}14`, border: `1px solid ${s.color}33` }}
              >
                {s.label}
              </span>
            </div>
            <p className="mt-1 text-xs text-faint">
              Impact brief · as of {brief.as_of.slice(0, 10)} · {brief.model ?? "—"} ·{" "}
              confidence <span className="text-muted">{brief.confidence ?? "—"}</span> · horizon{" "}
              <span className="text-muted">{brief.horizon ?? "—"}</span>
            </p>
          </div>
        </div>

        {brief.reject_reason && (
          <div className="panel mb-5 border-warn/40 p-4">
            <div className="text-[11px] uppercase tracking-wide text-warn">Rejected — reason</div>
            <div className="mt-1 text-sm text-muted">{brief.reject_reason}</div>
          </div>
        )}

        {/* summary */}
        <section className="panel mb-5 p-5">
          <div className="flex flex-wrap gap-1.5">
            {brief.mechanisms.map((mech) => (
              <span
                key={mech}
                className="rounded-md px-2 py-0.5 text-[11px] font-medium"
                style={{ color: "#2DD4BF", background: "#2DD4BF14", border: "1px solid #2DD4BF33" }}
              >
                {titleize(mech)}
              </span>
            ))}
          </div>
          {brief.summary && <p className="mt-3 text-[15px] leading-relaxed">{brief.summary}</p>}
        </section>

        {/* exposures */}
        <Panel title="Exposures" desc="Who is affected, in which revenue line and direction, and how big.">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-faint">
                  <th className="pb-2 pr-4 font-medium">Party</th>
                  <th className="pb-2 pr-4 font-medium">Revenue line</th>
                  <th className="pb-2 pr-4 font-medium">Direction</th>
                  <th className="pb-2 font-medium">Magnitude</th>
                </tr>
              </thead>
              <tbody>
                {brief.exposures.map((e, i) => (
                  <ExposureRow key={i} e={e} />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* transmission path */}
        <Panel title="Transmission path" desc="The explicit chain from the entity to each affected line.">
          <ol className="space-y-2">
            {brief.transmission_path.map((step, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className="tabular mt-0.5 text-xs text-faint">{i + 1}</span>
                <div>
                  <span className="text-text">{step.from_node}</span>
                  <span className="mx-2 text-faint">→</span>
                  <span className="text-text">{step.to_node}</span>
                  <div className="mt-0.5 text-xs text-muted">{step.effect}</div>
                </div>
              </li>
            ))}
          </ol>
        </Panel>

        {/* counter-mechanism */}
        <Panel
          title="Counter-mechanism"
          desc="The strongest case against the thesis, stated fairly — a one-sided brief is marketing."
        >
          <p className="text-sm leading-relaxed text-muted">{brief.counter_mechanism ?? "—"}</p>
        </Panel>

        {/* observables */}
        <Panel title="Observables" desc="Dated falsifiers that would settle the thesis. Prefer machine-measurable.">
          <div className="space-y-2">
            {brief.observables.map((o, i) => (
              <div key={i} className="rounded-md border border-border bg-surface p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm">{o.statement}</span>
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px]"
                    style={
                      o.source === "system"
                        ? { color: "#34D399", background: "#34D39914" }
                        : { color: "#94A3B8", background: "#94A3B814" }
                    }
                  >
                    {o.source}
                  </span>
                </div>
                <div className="mt-1 text-xs text-faint">
                  {o.horizon} · thesis holds ⇒ {o.direction_if_thesis_holds}
                  {o.system_metric ? ` · metric: ${o.system_metric}` : ""}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        {brief.evidence_refs.length > 0 && (
          <div className="mb-5 text-xs text-faint">
            Evidence: {brief.evidence_refs.length} raw event(s) —{" "}
            <span className="tabular">{brief.evidence_refs.slice(0, 12).join(", ")}</span>
            {brief.evidence_refs.length > 12 ? " …" : ""}
          </div>
        )}

        {/* review action bar */}
        <section className="panel p-5">
          <h2 className="text-sm font-semibold">Review</h2>
          <BriefActions briefId={brief.id} status={brief.status} />
        </section>
      </main>
    </>
  );
}

function ExposureRow({ e }: { e: BriefExposure }) {
  const color = DIRECTION[e.direction] ?? "#94A3B8";
  return (
    <tr className="border-t border-border">
      <td className="py-2 pr-4">
        <span className="font-medium">{e.ref}</span>
        <span className="ml-1 text-[10px] text-faint">{e.kind}</span>
      </td>
      <td className="py-2 pr-4 text-muted">{e.revenue_line ? titleize(e.revenue_line) : "—"}</td>
      <td className="py-2 pr-4">
        <span style={{ color }}>{e.direction}</span>
      </td>
      <td className="py-2 text-muted">{e.magnitude_class}</td>
    </tr>
  );
}

function Panel({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel mb-5 p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mb-3 mt-0.5 text-xs text-muted">{desc}</p>
      {children}
    </section>
  );
}
