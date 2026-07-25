import { titleize } from "@/lib/format";
import type { CouncilVerdictItem } from "@/lib/types";

const STANCE: Record<string, { label: string; color: string }> = {
  adopt: { label: "Adopt", color: "#34D399" },
  watch: { label: "Watch", color: "#F59E0B" },
  reject: { label: "Reject", color: "#F87171" },
  split: { label: "Split — no majority", color: "#94A3B8" },
};

const ROLE_LABEL: Record<string, string> = {
  skeptic: "Skeptic",
  evidence_auditor: "Evidence Auditor",
  mechanism_reviewer: "Mechanism Reviewer",
};

// Three independent perspectives deliberating on this brief (doc 08 §5) — not the brief author's
// own counter_mechanism self-critique, but genuinely separate calls that can disagree with each
// other and with the brief itself. Empty unless `seismo council` has reviewed this entity.
export function CouncilReview({
  verdicts,
  aggregate,
}: {
  verdicts: CouncilVerdictItem[];
  aggregate: string | null;
}) {
  if (verdicts.length === 0) {
    return (
      <section className="panel mb-5 p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Council review</h2>
        </div>
        <p className="mt-1 text-xs text-muted">
          Not yet reviewed. Three independent perspectives (skeptic, evidence auditor, mechanism
          reviewer) can deliberate on this brief separately — run{" "}
          <code className="text-accent">seismo council</code> to add it to the top-N watchlist.
        </p>
      </section>
    );
  }

  const agg = aggregate ? (STANCE[aggregate] ?? { label: aggregate, color: "#94A3B8" }) : null;

  return (
    <section className="panel mb-5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Council review</h2>
        {agg && (
          <span
            className="rounded-full px-2.5 py-0.5 text-[11px] font-medium"
            style={{ color: agg.color, background: `${agg.color}14`, border: `1px solid ${agg.color}33` }}
          >
            {agg.label}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-muted">
        Three independent LLM perspectives judging this brief separately — not the same model
        checking its own work. Majority vote is deterministic, computed here, never another LLM
        call.
      </p>
      <div className="mt-3 space-y-2">
        {verdicts.map((v) => {
          const s = STANCE[v.stance] ?? { label: v.stance, color: "#94A3B8" };
          return (
            <div key={v.role} className="rounded-md border border-border bg-surface p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{ROLE_LABEL[v.role] ?? titleize(v.role)}</span>
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                  style={{ color: s.color, background: `${s.color}14` }}
                >
                  {s.label}
                </span>
                <span className="text-[10px] text-faint">confidence: {v.confidence}</span>
                <span className="text-[10px] text-faint">· {v.model}</span>
              </div>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{v.reasoning}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
