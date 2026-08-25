import type { SustainedPoint } from "../types";
import { GiB } from "../format";

// Hand-rolled SVG line chart: write throughput vs cumulative data written.
// Reference lines show the marketing "sustained" claim and the USB link ceiling
// so an SLC-cache cliff (line diving below the claim) is obvious at a glance.
export function SustainedChart({
  points, claimMbps, ceilingMbps,
}: { points: SustainedPoint[]; claimMbps?: number | null; ceilingMbps?: number | null }) {
  const W = 820, H = 280, padL = 52, padR = 16, padT = 16, padB = 34;
  if (!points || points.length === 0) {
    return <div className="empty">No sustained-write samples. Enable the sustained test to map the SLC-cache cliff.</div>;
  }

  const maxBytes = Math.max(...points.map((p) => p.written_bytes));
  const refs = [claimMbps, ceilingMbps].filter((x): x is number => x != null);
  const maxY = Math.max(...points.map((p) => p.mbps), ...refs, 1) * 1.12;

  const x = (b: number) => padL + (b / maxBytes) * (W - padL - padR);
  const y = (v: number) => H - padB - (v / maxY) * (H - padT - padB);

  const line = points.map((p) => `${x(p.written_bytes).toFixed(1)},${y(p.mbps).toFixed(1)}`).join(" ");
  const area = `${padL},${H - padB} ${line} ${x(maxBytes).toFixed(1)},${H - padB}`;

  const yTicks = 4;
  const gridY = Array.from({ length: yTicks + 1 }, (_, i) => (maxY / yTicks) * i);
  const xTicks = Math.min(6, points.length);
  const gridX = Array.from({ length: xTicks + 1 }, (_, i) => (maxBytes / xTicks) * i);

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
          </linearGradient>
        </defs>

        {gridY.map((v, i) => (
          <g key={i}>
            <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke="#253243" strokeWidth="1" />
            <text x={padL - 8} y={y(v) + 4} textAnchor="end" fill="#6b7d92" fontSize="11" fontFamily="monospace">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {gridX.map((b, i) => (
          <text key={i} x={x(b)} y={H - padB + 18} textAnchor="middle" fill="#6b7d92" fontSize="11" fontFamily="monospace">
            {(b / GiB).toFixed(1)}
          </text>
        ))}
        <text x={(W) / 2} y={H - 4} textAnchor="middle" fill="#6b7d92" fontSize="11">
          Data written (GiB)
        </text>

        {ceilingMbps != null && (
          <line x1={padL} y1={y(ceilingMbps)} x2={W - padR} y2={y(ceilingMbps)} stroke="#c084fc" strokeWidth="1.4" strokeDasharray="6 4" />
        )}
        {claimMbps != null && (
          <line x1={padL} y1={y(claimMbps)} x2={W - padR} y2={y(claimMbps)} stroke="#fbbf24" strokeWidth="1.4" strokeDasharray="6 4" />
        )}

        <polygon points={area} fill="url(#areaGrad)" />
        <polyline points={line} fill="none" stroke="#38bdf8" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => (
          <circle key={i} cx={x(p.written_bytes)} cy={y(p.mbps)} r="2.6" fill="#22d3ee" />
        ))}
      </svg>
      <div className="chart-legend">
        <span className="li"><span className="swatch" style={{ background: "#38bdf8" }} /> Write throughput</span>
        {claimMbps != null && <span className="li"><span className="swatch" style={{ background: "#fbbf24" }} /> Sustained claim ({Math.round(claimMbps)})</span>}
        {ceilingMbps != null && <span className="li"><span className="swatch" style={{ background: "#c084fc" }} /> Link ceiling ({Math.round(ceilingMbps)})</span>}
      </div>
    </div>
  );
}
