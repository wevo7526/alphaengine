"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

interface MacroChartProps {
  title: string;
  data: { date: string; value: number }[];
  color: string;
  unit?: string;
  invertColor?: boolean;
}

export function MacroChart({
  title,
  data,
  color,
  unit = "",
  invertColor = false,
}: MacroChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="rounded-xl border border-border-primary bg-bg-surface p-4 h-48 flex items-center justify-center">
        <span className="text-xs text-text-quaternary">{title} — no data</span>
      </div>
    );
  }

  const latest = data[data.length - 1];
  const first = data[0];
  const change = latest.value - first.value;
  const isUp = change > 0;
  const changeColor = invertColor
    ? isUp ? "text-signal-red" : "text-signal-green"
    : isUp ? "text-signal-green" : "text-signal-red";

  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-[11px] text-text-quaternary uppercase tracking-wider">
            {title}
          </p>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-mono font-medium text-text-primary">
              {latest.value.toFixed(2)}{unit}
            </span>
            <span className={`text-xs font-mono ${changeColor}`}>
              {isUp ? "+" : ""}{change.toFixed(2)}
            </span>
          </div>
        </div>
        <span className="text-[11px] text-text-quaternary">{latest.date}</span>
      </div>

      <div style={{ width: "100%", height: 128, minWidth: 100 }}>
        <ResponsiveContainer width="100%" height={128}>
          <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={`gradient-${title}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.15} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(255,255,255,0.04)"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#52525b" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(d: string) => d.slice(5)}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#52525b" }}
              tickLine={false}
              axisLine={false}
              width={40}
              domain={["auto", "auto"]}
            />
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #27272a",
                borderRadius: "8px",
                fontSize: "12px",
                color: "#fafafa",
              }}
              formatter={(value) => [Number(value).toFixed(2) + unit, title]}
              labelFormatter={(label) => String(label)}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={1.5}
              fill={`url(#gradient-${title})`}
              dot={false}
              animationDuration={800}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
