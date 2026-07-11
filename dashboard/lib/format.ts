import type { MomentumState } from "./types";

// The momentum 5-scale — the one place these hues carry meaning (doc 10 §2).
export const STATE_META: Record<
  MomentumState,
  { label: string; color: string; rank: number }
> = {
  breakout: { label: "Breakout", color: "#34D399", rank: 0 },
  accelerating: { label: "Accelerating", color: "#2DD4BF", rank: 1 },
  simmering: { label: "Simmering", color: "#38BDF8", rank: 2 },
  fading: { label: "Fading", color: "#F59E0B", rank: 3 },
  dormant: { label: "Dormant", color: "#64748B", rank: 4 },
};

export const MATURITY_LADDER = [
  "idea_paper",
  "public_code",
  "usable_artifact",
  "distribution",
  "commercialization",
  "institutional_adoption",
];

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 100)}%`;
}

export function titleize(s: string | null | undefined): string {
  if (!s) return "—";
  return s
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function compactNum(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return String(Math.round(v));
}

export function shortDate(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}
