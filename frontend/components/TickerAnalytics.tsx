"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import type { TickerAnalytics as TickerAnalyticsData } from "@/lib/types";

function Sparkline({ data }: { data: { date: string; close: number }[] }) {
  if (!data || data.length < 2) return null;
  const first = data[0].close;
  const last = data[data.length - 1].close;
  const color = last >= first ? "#10b981" : "#ef4444";

  return (
    <div style={{ width: 112, height: 40 }}>
      <ResponsiveContainer width={112} height={40}>
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <defs>
            <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.2} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="close"
            stroke={color}
            strokeWidth={1.5}
            fill="url(#sparkGrad)"
            dot={false}
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function DrawdownChart({ data }: { data: { date: string; drawdown: number }[] }) {
  if (!data || data.length < 2) return null;

  return (
    <div style={{ width: "100%", height: 80, minWidth: 100 }}>
      <ResponsiveContainer width="100%" height={80}>
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <defs>
            <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0.2} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" hide />
          <YAxis hide domain={["auto", 0]} />
          <Tooltip
            contentStyle={{
              background: "#18181b",
              border: "1px solid #27272a",
              borderRadius: "8px",
              fontSize: "11px",
              color: "#fafafa",
            }}
            formatter={(value) => [`${Number(value).toFixed(2)}%`, "Drawdown"]}
            labelFormatter={(label) => String(label)}
          />
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="#ef4444"
            strokeWidth={1}
            fill="url(#ddGrad)"
            dot={false}
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function StatRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[11px] text-text-quaternary">{label}</span>
      <span className={`text-[11px] font-mono ${color ?? "text-text-primary"}`}>{value}</span>
    </div>
  );
}

export function TickerAnalyticsPanel({
  ticker,
  analytics,
}: {
  ticker: string;
  analytics: TickerAnalyticsData;
}) {
  if (analytics.error) return null;

  const vol = analytics.volatility;
  const dd = analytics.drawdown;

  return (
    <div
      className="rounded-xl border border-border-primary bg-bg-surface p-4"
      style={{ animation: "fade-in 0.4s ease-out" }}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-mono font-semibold text-text-primary">{ticker}</span>
        <Sparkline data={analytics.sparkline} />
      </div>

      {/* Key stats */}
      <div className="grid grid-cols-2 gap-x-6 mb-3">
        <StatRow
          label="Ann. Volatility"
          value={`${vol.realized_vol_annualized}%`}
          color={vol.realized_vol_annualized > 40 ? "text-signal-red" : "text-text-primary"}
        />
        <StatRow
          label="Ann. Return"
          value={`${vol.annualized_return > 0 ? "+" : ""}${vol.annualized_return}%`}
          color={vol.annualized_return >= 0 ? "text-signal-green" : "text-signal-red"}
        />
        <StatRow label="Sharpe" value={vol.sharpe_ratio.toFixed(2)} />
        <StatRow
          label="VaR (95%)"
          value={`${vol.var_95_daily}%`}
          color="text-signal-red"
        />
        <StatRow label="Skew" value={vol.skewness.toFixed(2)} />
        <StatRow
          label="Max Drawdown"
          value={`${dd.max_drawdown}%`}
          color="text-signal-red"
        />
        {analytics.sentiment && (
          <>
            <StatRow
              label="Sentiment"
              value={`${analytics.sentiment.compound > 0 ? "+" : ""}${analytics.sentiment.compound.toFixed(2)}`}
              color={analytics.sentiment.label === "positive" ? "text-signal-green" : analytics.sentiment.label === "negative" ? "text-signal-red" : "text-text-tertiary"}
            />
            <StatRow
              label="News Split"
              value={`${analytics.sentiment.bullish_pct}% bull / ${analytics.sentiment.bearish_pct}% bear`}
            />
          </>
        )}
      </div>

      {/* Drawdown chart */}
      {dd.series.length > 0 && (
        <div>
          <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">
            Drawdown from Peak
          </p>
          <DrawdownChart data={dd.series} />
        </div>
      )}
    </div>
  );
}
