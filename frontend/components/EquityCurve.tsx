"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

/**
 * EquityCurve — area chart of the portfolio's total value over time,
 * pulled from the EOD snapshot rollup (`/api/portfolio/equity-curve`).
 *
 * The line/fill colors follow the cumulative P&L sign so the chart
 * "looks" green/red at a glance. A horizontal reference line marks
 * the starting equity (the user's portfolio_base) so it's instantly
 * clear whether the book is up or down vs. day 0.
 */

interface EquityPoint {
  date: string;
  total_value: number;
  daily_pnl_pct: number;
  cumulative_pnl_pct: number;
}

export function EquityCurve({
  series,
  baseline,
  height = 220,
}: {
  series: EquityPoint[];
  baseline: number;
  height?: number;
}) {
  if (!series || series.length === 0) {
    return (
      <div
        className="rounded-md border border-border-primary bg-bg-primary/40 flex items-center justify-center"
        style={{ height }}
      >
        <div className="text-center max-w-sm px-6">
          <p className="text-[12px] text-text-tertiary mb-1">
            No EOD snapshots yet.
          </p>
          <p className="text-[11px] text-text-quaternary leading-relaxed">
            The first snapshot lands after market close each weekday.
            Use <span className="font-mono text-text-tertiary">Snapshot now</span> above
            to seed the curve with today&apos;s mark.
          </p>
        </div>
      </div>
    );
  }

  const latest = series[series.length - 1];
  const positive = latest.total_value >= baseline;
  const lineColor = positive ? "#10b981" : "#ef4444"; // signal-green / signal-red
  const gradientId = positive ? "equity-fill-up" : "equity-fill-down";

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={series}
        margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity={0.32} />
            <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis
          dataKey="date"
          stroke="#52525b"
          tick={{ fill: "#71717a", fontSize: 10 }}
          tickFormatter={(d) => {
            // YYYY-MM-DD → "MMM D"
            try {
              const dt = new Date(d);
              return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
            } catch {
              return d;
            }
          }}
          minTickGap={32}
        />
        <YAxis
          stroke="#52525b"
          tick={{ fill: "#71717a", fontSize: 10 }}
          tickFormatter={(v) => {
            if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
            if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
            return `$${v.toFixed(0)}`;
          }}
          domain={["auto", "auto"]}
          width={56}
        />
        <Tooltip
          contentStyle={{
            background: "#18181b",
            border: "1px solid #27272a",
            borderRadius: 6,
            fontSize: 11,
            color: "#fafafa",
          }}
          labelStyle={{ color: "#a1a1aa", fontSize: 10, marginBottom: 4 }}
          formatter={(value, name) => {
            const v = typeof value === "number" ? value : Number(value ?? 0);
            const n = String(name ?? "");
            if (n === "total_value") {
              return [`$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, "Equity"];
            }
            return [`${v.toFixed(2)}%`, n];
          }}
          labelFormatter={(d) => {
            try {
              return new Date(d).toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              });
            } catch {
              return d;
            }
          }}
        />
        <ReferenceLine
          y={baseline}
          stroke="#3f3f46"
          strokeDasharray="3 3"
          label={{
            value: "BASELINE",
            position: "insideTopRight",
            fill: "#52525b",
            fontSize: 9,
            fontFamily: "ui-monospace, monospace",
          }}
        />
        <Area
          type="monotone"
          dataKey="total_value"
          stroke={lineColor}
          strokeWidth={1.6}
          fill={`url(#${gradientId})`}
          dot={false}
          activeDot={{ r: 3, fill: lineColor, strokeWidth: 0 }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
