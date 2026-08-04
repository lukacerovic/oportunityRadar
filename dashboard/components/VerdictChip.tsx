// Outcome verdicts for a wave. `unmeasurable` is deliberately styled as neutral information, not
// as a failure: npm isn't collected and PyPI is Python-only, so "nothing to measure" is a real
// state of the world and must never read like "it flopped".
const META: Record<string, { label: string; className: string; hint: string }> = {
  took_hold: {
    label: "took hold",
    className: "border-positive/40 bg-positive/10 text-positive",
    hint: "Members out-grew their own cohorts over the horizon",
  },
  flat: {
    label: "flat",
    className: "border-border bg-bg text-muted",
    hint: "Members grew about as fast as their cohorts — no signal either way",
  },
  faded: {
    label: "faded",
    className: "border-negative/40 bg-negative/10 text-negative",
    hint: "Members grew more slowly than their cohorts",
  },
  unmeasurable: {
    label: "unmeasurable",
    className: "border-border bg-bg text-faint",
    hint: "No usage metric covers these members, or the horizon hasn't elapsed yet",
  },
};

export function VerdictChip({ verdict }: { verdict: string }) {
  const meta = META[verdict] ?? {
    label: verdict,
    className: "border-border bg-bg text-muted",
    hint: "",
  };
  return (
    <span
      title={meta.hint}
      className={`rounded-md border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${meta.className}`}
    >
      {meta.label}
    </span>
  );
}
