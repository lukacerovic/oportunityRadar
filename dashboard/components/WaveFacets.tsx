import Link from "next/link";
import type { ThemeFacet } from "@/lib/types";

// Facets, not a tree. A wave can carry two themes at once — the known convergence spanned "agent
// tooling" and "retrieval & memory" — so selecting a theme filters whole waves rather than
// descending into a branch. Descending would have shown four of its six members and hidden the
// rest, which is the finding cut in half by the navigation.

const VERDICTS = [
  { value: "took_hold", label: "took hold" },
  { value: "faded", label: "faded" },
  { value: "flat", label: "flat" },
  { value: "ungraded", label: "not graded yet" },
];

function chipHref(
  current: { theme?: string; verdict?: string; minLead?: string },
  patch: Record<string, string | undefined>,
): string {
  const q = new URLSearchParams();
  const next = { ...current, ...patch };
  if (next.theme) q.set("theme", next.theme);
  if (next.verdict) q.set("verdict", next.verdict);
  if (next.minLead) q.set("min_lead", next.minLead);
  const s = q.toString();
  return s ? `/waves?${s}` : "/waves";
}

function Chip({
  href,
  on,
  children,
  title,
}: {
  href: string;
  on: boolean;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <Link
      href={href}
      title={title}
      className={`rounded-md border px-2 py-1 text-xs transition ${
        on
          ? "border-accent/60 bg-accent/10 text-text"
          : "border-border bg-card text-muted hover:text-text"
      }`}
    >
      {children}
    </Link>
  );
}

export function WaveFacets({
  themes,
  active,
}: {
  themes: ThemeFacet[];
  active: { theme?: string; verdict?: string; minLead?: string };
}) {
  const anyActive = active.theme || active.verdict || active.minLead;
  return (
    <div className="mb-5 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[10px] uppercase tracking-wide text-faint">theme</span>
        {themes.map((t) => (
          <Chip
            key={t.name}
            href={chipHref(active, { theme: active.theme === t.name ? undefined : t.name })}
            on={active.theme === t.name}
            title={t.description}
          >
            {t.name} <span className="tabular text-faint">{t.wave_count}</span>
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[10px] uppercase tracking-wide text-faint">outcome</span>
        {VERDICTS.map((v) => (
          <Chip
            key={v.value}
            href={chipHref(active, {
              verdict: active.verdict === v.value ? undefined : v.value,
            })}
            on={active.verdict === v.value}
          >
            {v.label}
          </Chip>
        ))}

        <span className="ml-3 mr-1 text-[10px] uppercase tracking-wide text-faint">lead</span>
        {["7", "14", "30"].map((d) => (
          <Chip
            key={d}
            href={chipHref(active, { minLead: active.minLead === d ? undefined : d })}
            on={active.minLead === d}
            title={`Only waves discussed at least ${d} days before we detected them`}
          >
            ≥{d}d
          </Chip>
        ))}

        {anyActive && (
          <Link href="/waves" className="ml-2 text-xs text-muted underline hover:text-text">
            clear
          </Link>
        )}
      </div>
    </div>
  );
}
