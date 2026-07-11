import type { MaturityRung, SparkPoint } from "@/lib/types";
import { compactNum, shortDate } from "@/lib/format";

// SVG area chart matching the reference "Valuation Trajectory": cyan area, gridlines, promotions
// rendered as reference dots on the line (doc 10 §2).
export function MetricChart({
  points,
  promotions = [],
  height = 240,
}: {
  points: SparkPoint[];
  promotions?: MaturityRung[];
  height?: number;
}) {
  if (points.length < 2) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-faint">
        Not enough history to plot — needs ≥2 daily points.
      </div>
    );
  }
  const W = 720;
  const H = height;
  const padL = 44;
  const padB = 24;
  const padT = 12;
  const xs = points.map((p) => new Date(p.day).getTime());
  const ys = points.map((p) => p.value);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs) || xMin + 1;
  const yMax = Math.max(...ys) * 1.08 || 1;
  const px = (t: number) => padL + ((t - xMin) / (xMax - xMin || 1)) * (W - padL - 8);
  const py = (v: number) => padT + (1 - v / yMax) * (H - padT - padB);

  const line = points.map((p, i) => `${i ? "L" : "M"} ${px(xs[i])},${py(p.value)}`).join(" ");
  const area = `${line} L ${px(xMax)},${H - padB} L ${px(xMin)},${H - padB} Z`;
  const gridVals = [0.25, 0.5, 0.75, 1].map((f) => f * yMax);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <defs>
        <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22D3EE" stopOpacity="0.32" />
          <stop offset="100%" stopColor="#22D3EE" stopOpacity="0" />
        </linearGradient>
      </defs>
      {gridVals.map((v, i) => (
        <g key={i}>
          <line
            x1={padL}
            x2={W - 8}
            y1={py(v)}
            y2={py(v)}
            stroke="#1E2A2C"
            strokeDasharray="2 4"
          />
          <text x={8} y={py(v) + 3} fill="#55686B" fontSize="10" className="tabular">
            {compactNum(v)}
          </text>
        </g>
      ))}
      <path d={area} fill="url(#area)" />
      <path d={line} fill="none" stroke="#22D3EE" strokeWidth="2" strokeLinejoin="round" />
      {promotions.map((p, i) => {
        const t = new Date(p.promoted_at).getTime();
        if (t < xMin || t > xMax) return null;
        // ride the promotion dot on the nearest data point
        let nearest = points[0];
        for (const pt of points) {
          if (Math.abs(new Date(pt.day).getTime() - t) < Math.abs(new Date(nearest.day).getTime() - t))
            nearest = pt;
        }
        return (
          <g key={i}>
            <circle cx={px(t)} cy={py(nearest.value)} r="4" fill="#34D399" stroke="#0A0E0F" strokeWidth="1.5">
              <title>{`${p.stage} · ${shortDate(p.promoted_at)}`}</title>
            </circle>
          </g>
        );
      })}
      <text x={padL} y={H - 6} fill="#55686B" fontSize="10" className="tabular">
        {shortDate(points[0].day)}
      </text>
      <text x={W - 8} y={H - 6} fill="#55686B" fontSize="10" textAnchor="end" className="tabular">
        {shortDate(points[points.length - 1].day)}
      </text>
    </svg>
  );
}
