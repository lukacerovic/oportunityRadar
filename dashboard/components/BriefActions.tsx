"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const BASE = process.env.SEISMO_API_BASE ?? "http://127.0.0.1:8000";

// Draft → review → publish/reject (DR-08.2). Only a draft is actionable; a decided brief is
// immutable, so the bar collapses to a status note once reviewed.
export function BriefActions({ briefId, status }: { briefId: number; status: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  if (status !== "draft") {
    return (
      <div className="mt-2 text-xs text-faint">
        This brief is <span className="text-muted">{status}</span> — published and rejected briefs
        are immutable. A re-gate creates a new version.
      </div>
    );
  }

  async function decide(decision: "publish" | "reject") {
    if (decision === "reject" && !reason.trim()) {
      setRejecting(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const q = new URLSearchParams({ decision });
      if (decision === "reject") q.set("reason", reason.trim());
      const res = await fetch(`${BASE}/briefs/${briefId}/decision?${q.toString()}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      router.refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => decide("publish")}
          disabled={busy}
          className="rounded-md px-4 py-2 text-sm font-medium text-bg transition disabled:opacity-50"
          style={{ background: "#34D399" }}
        >
          Publish
        </button>
        <button
          onClick={() => decide("reject")}
          disabled={busy}
          className="rounded-md border px-4 py-2 text-sm font-medium transition disabled:opacity-50"
          style={{ color: "#F59E0B", borderColor: "#F59E0B55" }}
        >
          Reject
        </button>
        <span className="text-xs text-faint">
          Publishing makes the brief immutable. Rejection keeps the draft + reason for the quality
          loop.
        </span>
      </div>
      {rejecting && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for rejection (required)…"
            className="min-w-[280px] flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <button
            onClick={() => decide("reject")}
            disabled={busy || !reason.trim()}
            className="rounded-md border px-3 py-2 text-sm transition disabled:opacity-40"
            style={{ color: "#F59E0B", borderColor: "#F59E0B55" }}
          >
            Confirm reject
          </button>
        </div>
      )}
      {error && (
        <div className="mt-2 text-xs text-warn">
          {error} — start the API with <code className="text-accent">uv run seismo serve</code>.
        </div>
      )}
    </div>
  );
}
