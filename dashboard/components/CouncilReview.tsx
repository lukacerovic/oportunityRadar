"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { titleize } from "@/lib/format";
import type { CouncilVerdictItem } from "@/lib/types";

const BASE = process.env.SEISMO_API_BASE ?? "http://127.0.0.1:8000";

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
  entityId,
  verdicts,
  aggregate,
}: {
  entityId: number;
  verdicts: CouncilVerdictItem[];
  aggregate: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runNow() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${BASE}/briefs/${entityId}/council`, { method: "POST" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      router.refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (verdicts.length === 0) {
    return (
      <section className="panel mb-5 p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Council review</h2>
        </div>
        <p className="mt-1 text-xs text-muted">
          Not yet reviewed. Three independent perspectives (skeptic, evidence auditor, mechanism
          reviewer) can deliberate on this brief — triggered only for this one entity, right now,
          never as part of a batch (three LLM calls, so it only runs when someone actually asks).
        </p>
        <button
          onClick={runNow}
          disabled={busy}
          className="mt-3 rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg transition disabled:opacity-50"
        >
          {busy ? "Running council review…" : "Run council review"}
        </button>
        {error && (
          <div className="mt-2 text-xs text-warn">
            {error} — start the API with <code className="text-accent">uv run seismo serve</code>.
          </div>
        )}
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
