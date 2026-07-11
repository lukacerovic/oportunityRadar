import Link from "next/link";

const NAV = [
  { href: "/", label: "Radar" },
  { href: "/changes/latest", label: "Changes" },
  { href: "/gate/current", label: "Gate" },
  { href: "/brief", label: "Briefs" },
  { href: "/queue", label: "Queue" },
];

export function TopNav({ active = "/" }: { active?: string }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-6 border-b border-border bg-bg/80 px-5 backdrop-blur">
      <Link href="/" className="flex items-center gap-2.5">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-gradient-to-br from-accent to-positive text-bg">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
            <path d="M3 12h3l2 6 4-16 3 12 2-4h4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <span className="text-[15px] font-semibold tracking-tight">Seismograph</span>
        <span className="rounded-md border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
          Frontier Intel
        </span>
      </Link>
      <nav className="flex items-center gap-1 text-sm">
        {NAV.map((n) => {
          const on = n.href === active;
          return (
            <Link
              key={n.href}
              href={n.href}
              className={`rounded-md px-3 py-1.5 transition ${
                on
                  ? "bg-card text-text shadow-[0_0_0_1px_theme(colors.border)]"
                  : "text-muted hover:text-text"
              }`}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
      <div className="ml-auto flex items-center gap-2 text-[11px] text-muted">
        <span className="h-2 w-2 rounded-full bg-positive shadow-[0_0_8px_#34D399]" />
        daily heartbeat
      </div>
    </header>
  );
}
