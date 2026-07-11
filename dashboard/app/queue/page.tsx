"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { titleize } from "@/lib/format";
import type { QueueItem } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { InfoButton } from "@/components/InfoModal";
import { HELP } from "@/lib/help";

const BASE = process.env.SEISMO_API_BASE ?? "http://127.0.0.1:8000";

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [idx, setIdx] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(0);

  useEffect(() => {
    fetch(`${BASE}/queue`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API ${r.status}`))))
      .then(setItems)
      .catch((e) => setError(String(e)));
  }, []);

  const decide = useCallback(
    async (decision: "merge" | "reject" | "skip") => {
      const item = items[idx];
      if (!item) return;
      try {
        await fetch(`${BASE}/merge-queue/${item.id}/decision?decision=${decision}`, {
          method: "POST",
        });
        setDone((d) => d + 1);
        setIdx((i) => i + 1);
      } catch (e) {
        setError(String(e));
      }
    },
    [items, idx],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "m" || e.key === "M") decide("merge");
      else if (e.key === "n" || e.key === "N") decide("reject");
      else if (e.key === "s" || e.key === "S") decide("skip");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide]);

  const item = items[idx];

  return (
    <>
      <TopNav active="/queue" />
      <main className="mx-auto max-w-3xl px-5 py-6">
        <div className="mb-5 flex items-end justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">Merge Queue</h1>
              <InfoButton content={HELP.queue} />
            </div>
            <p className="mt-1 text-sm text-muted">
              Name-backed candidates (R4–R5) for a human call. Keyboard:{" "}
              <Kbd>M</Kbd> merge · <Kbd>N</Kbd> reject · <Kbd>S</Kbd> skip.
            </p>
          </div>
          <div className="tabular text-sm text-muted">
            {done} decided · {Math.max(items.length - idx, 0)} left
          </div>
        </div>

        {error && (
          <div className="panel p-5 text-sm text-warn">
            {error} — start the API with <code className="text-accent">uv run seismo serve</code>.
          </div>
        )}

        {!error && !item && (
          <div className="panel p-10 text-center text-sm text-muted">
            {items.length === 0 && done === 0
              ? "Queue is empty — nothing awaiting triage."
              : "All caught up. Nice throughput."}
          </div>
        )}

        {item && (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-3 text-xs text-faint">
              <span>rule {String(item.evidence.rule ?? "?")}</span>
              <span>·</span>
              <span className="tabular">confidence {Math.round(item.confidence * 100)}%</span>
            </div>
            <div className="grid grid-cols-[1fr_auto_1fr] items-stretch gap-3">
              <Candidate item={item} side="a" />
              <div className="flex items-center text-2xl font-light text-faint">≟</div>
              <Candidate item={item} side="b" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Action label="Merge" hint="M" color="#34D399" onClick={() => decide("merge")} />
              <Action label="Reject" hint="N" color="#F59E0B" onClick={() => decide("reject")} />
              <Action label="Skip" hint="S" color="#64748B" onClick={() => decide("skip")} />
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function Candidate({ item, side }: { item: QueueItem; side: "a" | "b" }) {
  const e = side === "a" ? item.entity_a : item.entity_b;
  return (
    <Link href={`/entity/${e.id}`} className="panel p-4 transition hover:bg-card-hover">
      <div className="truncate text-[15px] font-semibold">{e.name}</div>
      <div className="mt-1 text-xs text-muted">
        {titleize(e.category)} · {e.entity_type}
      </div>
      <div className="mt-3 text-xs text-faint">owner · {e.owner ?? "—"}</div>
    </Link>
  );
}

function Action({
  label,
  hint,
  color,
  onClick,
}: {
  label: string;
  hint: string;
  color: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="panel flex flex-col items-center gap-1 py-4 transition hover:bg-card-hover"
      style={{ borderColor: `${color}44` }}
    >
      <span className="text-sm font-medium" style={{ color }}>
        {label}
      </span>
      <Kbd>{hint}</Kbd>
    </button>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-surface px-1.5 py-0.5 text-[10px] text-muted">
      {children}
    </kbd>
  );
}
