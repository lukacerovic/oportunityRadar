"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { ScorePacketResponse } from "@/lib/types";

const BASE = process.env.SEISMO_API_BASE ?? "http://127.0.0.1:8000";

// Auto-eval status → colour (A-7). on_track good, counter bad, the rest neutral/pending.
const STATUS: Record<string, string> = {
  on_track: "#34D399",
  counter: "#F87171",
  flat: "#94A3B8",
  too_early: "#64748B",
  unmeasurable: "#64748B",
  operator_judgment: "#38BDF8",
};

// The quarterly forward-scoring ritual (doc 09 §2, DR-09.2). Auto-evaluates the system observables
// for the operator, who records the verdict. Shown once a brief is published.
export function BriefScoring({ entityId }: { entityId: number }) {
  const router = useRouter();
  const [packet, setPacket] = useState<ScorePacketResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [materialized, setMaterialized] = useState("too_early");
  const [falsifier, setFalsifier] = useState(false);
  const [counter, setCounter] = useState(false);
  const [verdict, setVerdict] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${BASE}/briefs/${entityId}/score-packet`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API ${r.status}`))))
      .then((p: ScorePacketResponse) => {
        setPacket(p);
        if (p.existing_score?.materialized) setMaterialized(p.existing_score.materialized);
        if (p.existing_score?.falsifier_tripped) setFalsifier(true);
        if (p.existing_score?.counter_was_better) setCounter(true);
        if (p.existing_score?.verdict) setVerdict(p.existing_score.verdict);
      })
      .catch((e) => setError(String(e)));
  }, [entityId]);

  if (error) return <div className="mt-2 text-xs text-warn">{error}</div>;
  if (!packet) return <div className="mt-2 text-xs text-faint">Loading scoring context…</div>;

  async function save() {
    if (!packet) return;
    setBusy(true);
    setError(null);
    try {
      const q = new URLSearchParams({
        materialized,
        falsifier_tripped: String(falsifier),
        counter_was_better: String(counter),
      });
      if (verdict.trim()) q.set("verdict", verdict.trim());
      const res = await fetch(`${BASE}/briefs/${packet.brief_id}/score?${q.toString()}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      setSaved(true);
      router.refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-faint">{packet.days_elapsed}d since publication</span>
        <span className="text-faint">·</span>
        <span className="text-muted">{packet.auto_summary}</span>
      </div>

      {/* observable auto-evaluation (A-7) */}
      <div className="space-y-1.5">
        {packet.observable_evals.map((ev, i) => (
          <div key={i} className="rounded-md border border-border bg-surface p-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                style={{
                  color: STATUS[ev.status] ?? "#94A3B8",
                  background: `${STATUS[ev.status] ?? "#94A3B8"}14`,
                }}
              >
                {ev.status.replace(/_/g, " ")}
              </span>
              <span className="text-sm">{ev.statement}</span>
            </div>
            {ev.detail && <div className="mt-1 text-[11px] text-faint">{ev.detail}</div>}
          </div>
        ))}
      </div>

      {/* operator verdict */}
      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-faint">Did the exposure materialize?</span>
          {["yes", "partial", "no", "too_early"].map((v) => (
            <button
              key={v}
              onClick={() => setMaterialized(v)}
              className="rounded-md border px-2.5 py-1 text-xs transition"
              style={
                materialized === v
                  ? { background: "#2DD4BF", borderColor: "#2DD4BF", color: "#0A0F0F" }
                  : { borderColor: "#1E2A2C" }
              }
            >
              {v.replace(/_/g, " ")}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={falsifier} onChange={(e) => setFalsifier(e.target.checked)} />
            a falsifier tripped
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={counter} onChange={(e) => setCounter(e.target.checked)} />
            counter-mechanism was the better story
          </label>
        </div>
        <textarea
          value={verdict}
          onChange={(e) => setVerdict(e.target.value)}
          placeholder="Free-text verdict (optional)…"
          className="min-h-[64px] w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <div className="flex items-center gap-3">
          <button
            onClick={save}
            disabled={busy}
            className="rounded-md px-4 py-2 text-sm font-medium text-bg transition disabled:opacity-50"
            style={{ background: "#2DD4BF" }}
          >
            {packet.existing_score ? "Update score" : "Record score"}
          </button>
          {saved && <span className="text-xs text-positive">saved ✓</span>}
        </div>
      </div>
    </div>
  );
}
