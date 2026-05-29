"use client";

/**
 * Sparkline — tiny inline area chart for the open-positions table.
 *
 * Pure SVG so it renders quickly in dense tables (Recharts spins up a
 * ResponsiveContainer per instance which is heavier than needed at
 * 60×16 px). Color follows the sign of the last value vs. zero.
 */

interface SparklinePoint {
  date: string;
  unrealized_pnl_pct: number;
}

export function Sparkline({
  data,
  width = 64,
  height = 18,
  positiveColor = "#10b981", // signal-green
  negativeColor = "#ef4444", // signal-red
  neutralColor = "#52525b",  // text-quaternary
}: {
  data: SparklinePoint[];
  width?: number;
  height?: number;
  positiveColor?: string;
  negativeColor?: string;
  neutralColor?: string;
}) {
  if (!data || data.length === 0) {
    return (
      <span
        className="inline-block"
        style={{ width, height }}
        title="No snapshot history yet"
      >
        <svg width={width} height={height} aria-hidden>
          <line
            x1={0}
            y1={height / 2}
            x2={width}
            y2={height / 2}
            stroke={neutralColor}
            strokeWidth={1}
            strokeDasharray="2 3"
            opacity={0.4}
          />
        </svg>
      </span>
    );
  }

  // Use unrealized_pnl_pct so the sparkline reads as "trajectory of
  // return %" not "absolute equity". Easier to compare across positions.
  const values = data.map((d) => d.unrealized_pnl_pct);
  const last = values[values.length - 1];

  // Normalize to chart bounds. Center the zero line so positive shows
  // as upward sweep and negative as downward.
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const pad = 1.5; // top/bottom padding in px

  const stepX = data.length > 1 ? width / (data.length - 1) : width;
  const toY = (v: number) =>
    pad + (height - 2 * pad) * (1 - (v - min) / range);

  const points = values.map((v, i) => `${i * stepX},${toY(v).toFixed(2)}`).join(" ");
  const zeroY = toY(0);

  const stroke =
    last > 0 ? positiveColor : last < 0 ? negativeColor : neutralColor;

  const last0 = values[0];
  const fillStartId = `spark-fill-${stroke.slice(1)}`;

  // Build a closed area path so we can fill the region between the
  // line and the zero baseline.
  const areaPath =
    `M0,${zeroY.toFixed(2)} ` +
    values.map((v, i) => `L${i * stepX},${toY(v).toFixed(2)}`).join(" ") +
    ` L${(values.length - 1) * stepX},${zeroY.toFixed(2)} Z`;

  return (
    <svg
      width={width}
      height={height}
      aria-label={`Sparkline: started ${last0.toFixed(2)}%, latest ${last.toFixed(2)}%`}
      role="img"
    >
      <defs>
        <linearGradient id={fillStartId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
          <stop offset="100%" stopColor={stroke} stopOpacity={0} />
        </linearGradient>
      </defs>
      {/* Zero baseline */}
      <line
        x1={0}
        y1={zeroY}
        x2={width}
        y2={zeroY}
        stroke={neutralColor}
        strokeWidth={0.5}
        strokeDasharray="2 2"
        opacity={0.5}
      />
      <path d={areaPath} fill={`url(#${fillStartId})`} />
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={1.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
