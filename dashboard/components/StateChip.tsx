import { STATE_META } from "@/lib/format";
import type { MomentumState } from "@/lib/types";

export function StateChip({
  state,
  provisional = false,
  size = "sm",
}: {
  state: MomentumState;
  provisional?: boolean;
  size?: "sm" | "md";
}) {
  const meta = STATE_META[state];
  const pad = size === "md" ? "px-2.5 py-1 text-xs" : "px-2 py-0.5 text-[11px]";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${pad}`}
      style={{
        color: meta.color,
        background: `${meta.color}14`,
        border: `1px solid ${meta.color}33`,
      }}
      title={provisional ? "Provisional — cohort still warming up" : meta.label}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: meta.color, boxShadow: `0 0 8px ${meta.color}` }}
      />
      {meta.label}
      {provisional && <span className="opacity-60">·prov</span>}
    </span>
  );
}
