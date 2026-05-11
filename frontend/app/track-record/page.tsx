"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LineChart,
  Line,
  Legend,
  ReferenceLine,
} from "recharts";

// Threshold above which we consider the IC stable enough to publish.
// Below this we still show data, but flagged as "low_sample".
const STABLE_IC_MIN_SIGNALS = 20;

interface ConvictionBucket {
  count: number;
  hit_rate_5d?: number | null;
  avg_return_5d?: number | null;
}

interface ScorecardSummary {
  signals: number;
  hit_rate_1d: number | null;
  hit_rate_5d: number | null;
  hit_rate_20d: number | null;
  avg_return_1d: number | null;
  avg_return_5d: number | null;
  avg_return_20d: number | null;
  ic_5d: number | null;
  ic_20d: number | null;
  by_conviction: Record<string, ConvictionBucket>;
  top_winners: Array<{
    ticker: string;
    direction: string;
    conviction: number;
    return_20d: number | null;
    signal_date: string | null;
  }>;
  top_losers: Array<{
    ticker: string;
    direction: string;
    conviction: number;
    return_20d: number | null;
    signal_date: string | null;
  }>;
  error?: string;
}

interface SignalScore {
  id: string;
  ticker: string;
  direction: string;
  conviction: number;
  entry_price: number | null;
  signal_date: string | null;
  return_1d: number | null;
  return_5d: number | null;
  return_20d: number | null;
  hit_1d: boolean | null;
  hit_5d: boolean | null;
  hit_20d: boolean | null;
}

interface SignalsResp {
  signals: SignalScore[];
  count: number;
}

interface AttributionData {
  trade_count: number;
  unique_tickers?: number;
  period_return_pct?: number;
  benchmark_return_pct?: number;
  decomposition?: {
    alpha_pct: number | null;
    beta_contribution_pct: number;
    residual_pct: number;
  };
  factor_loadings?: {
    alpha: number | null;
    beta: number | null;
    r_squared: number | null;
    residual_vol: number | null;
  };
  weights?: Record<string, number>;
  error?: string;
}

interface FactorResp {
  tickers: string[];
  model: string;
  alpha?: number | null;
  beta?: number | null;
  r_squared?: number | null;
  residual_vol?: number | null;
  factor_betas?: Record<string, number>;
  alpha_pvalue?: number | null;
  alpha_tstat?: number | null;
  alpha_significant_at_5pct?: boolean;
  n_observations?: number;
  multi_factor?: {
    alpha?: number | null;
    alpha_pvalue?: number | null;
    alpha_significant_at_5pct?: boolean;
    factor_betas?: Record<string, number>;
    factor_tstats?: Record<string, number>;
    r_squared?: number | null;
    adj_r_squared?: number | null;
    residual_vol?: number | null;
    model?: string;
    n_observations?: number;
    multicollinearity_flag?: boolean;
    high_vif_factors?: string[];
    error?: string;
  };
}

interface PositionsResp {
  positions: { ticker: string }[];
}

function Stat({
  label,
  value,
  suffix,
  color,
  help,
}: {
  label: string;
  value: string | null;
  suffix?: string;
  color?: string;
  help?: string;
}) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <p
        className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1"
        title={help}
      >
        {label}
        {help && <span className="ml-1 text-text-quaternary cursor-help">ⓘ</span>}
      </p>
      <p className={`text-lg font-mono font-medium ${color ?? "text-text-primary"}`}>
        {value ?? "—"}
        {suffix}
      </p>
    </div>
  );
}

function fmtPct(v: number | null | undefined, digits = 1): string | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return `${v.toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 3): string | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return v.toFixed(digits);
}

function fmtReturn(v: number | null | undefined): string | null {
  // Returns from scorer are stored as decimals (e.g., 0.0234 = 2.34%)
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return `${(v * 100).toFixed(2)}%`;
}

function returnColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-text-secondary";
  if (v > 0) return "text-signal-green";
  if (v < 0) return "text-signal-red";
  return "text-text-secondary";
}

function aggregateHitRateByMonth(signals: SignalScore[]) {
  // Group by YYYY-MM of signal_date; compute hit_rate_5d per bucket
  const buckets: Record<string, { hits: number; total: number; sum_ret: number; n_ret: number }> = {};
  for (const s of signals) {
    if (!s.signal_date) continue;
    const month = s.signal_date.slice(0, 7); // YYYY-MM
    if (!buckets[month]) buckets[month] = { hits: 0, total: 0, sum_ret: 0, n_ret: 0 };
    if (s.hit_5d !== null && s.hit_5d !== undefined) {
      buckets[month].total += 1;
      if (s.hit_5d) buckets[month].hits += 1;
    }
    if (s.return_5d !== null && s.return_5d !== undefined && !Number.isNaN(s.return_5d)) {
      buckets[month].sum_ret += s.return_5d;
      buckets[month].n_ret += 1;
    }
  }
  return Object.entries(buckets)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, b]) => ({
      month,
      hit_rate_5d: b.total > 0 ? (b.hits / b.total) * 100 : null,
      avg_return_5d: b.n_ret > 0 ? (b.sum_ret / b.n_ret) * 100 : null,
      n_signals: b.total,
    }));
}

export default function TrackRecordPage() {
  const [summary, setSummary] = useState<ScorecardSummary | null>(null);
  const [signals, setSignals] = useState<SignalScore[]>([]);
  const [attribution, setAttribution] = useState<AttributionData | null>(null);
  const [factors, setFactors] = useState<FactorResp | null>(null);
  const [factorModel, setFactorModel] = useState<"single" | "ff5_mom">("single");
  const [factorLoading, setFactorLoading] = useState(false);
  const [openTickers, setOpenTickers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, sigResp, attr, pos] = await Promise.all([
        api.scorecardSummary() as Promise<ScorecardSummary>,
        api.scorecardSignals(200) as Promise<SignalsResp>,
        api.attribution().catch(() => null) as Promise<AttributionData | null>,
        api.positions().catch(() => null) as Promise<PositionsResp | null>,
      ]);
      setSummary(s);
      setSignals(sigResp?.signals ?? []);
      setAttribution(attr);
      const tickers = Array.from(
        new Set((pos?.positions ?? []).map((p) => p.ticker).filter(Boolean))
      ).slice(0, 8);
      setOpenTickers(tickers);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load track record";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function loadFactors(model: "single" | "ff5_mom") {
    if (openTickers.length === 0) {
      setError("Factor exposure needs at least one open position.");
      return;
    }
    setFactorLoading(true);
    try {
      const f = (await api.factors(openTickers, model)) as FactorResp;
      setFactors(f);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Factor regression failed";
      setError(msg);
    } finally {
      setFactorLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function runScoring() {
    setRunning(true);
    try {
      await api.scorecardRun();
      await load();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Scoring failed";
      setError(msg);
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 text-text-secondary">
        Loading scorecard…
      </div>
    );
  }

  const nSignals = summary?.signals ?? 0;
  const stable = nSignals >= STABLE_IC_MIN_SIGNALS;

  // Build conviction-bucket chart data
  const convictionData = summary
    ? Object.entries(summary.by_conviction).map(([name, b]) => ({
        bucket: name,
        count: b.count,
        hit_rate_5d: b.hit_rate_5d ?? null,
        // returns from scorer are decimals — convert to %
        avg_return_5d_pct: b.avg_return_5d !== null && b.avg_return_5d !== undefined
          ? b.avg_return_5d * 100
          : null,
      }))
    : [];

  // Build alpha decay chart data (1d/5d/20d hit rates and avg returns)
  const decayData = summary
    ? [
        {
          horizon: "1d",
          hit_rate: summary.hit_rate_1d ?? null,
          avg_return_pct:
            summary.avg_return_1d !== null && summary.avg_return_1d !== undefined
              ? summary.avg_return_1d * 100
              : null,
        },
        {
          horizon: "5d",
          hit_rate: summary.hit_rate_5d ?? null,
          avg_return_pct:
            summary.avg_return_5d !== null && summary.avg_return_5d !== undefined
              ? summary.avg_return_5d * 100
              : null,
        },
        {
          horizon: "20d",
          hit_rate: summary.hit_rate_20d ?? null,
          avg_return_pct:
            summary.avg_return_20d !== null && summary.avg_return_20d !== undefined
              ? summary.avg_return_20d * 100
              : null,
        },
      ]
    : [];

  const monthlyData = aggregateHitRateByMonth(signals);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Track Record</h1>
          <p className="text-[12px] text-text-tertiary mt-1">
            The system grading itself. Every past trade idea scored at 1d / 5d / 20d
            against realized prices.
          </p>
        </div>
        <button
          onClick={runScoring}
          disabled={running}
          className="rounded-lg px-3 py-1.5 text-[12px] font-medium bg-white/[0.07] hover:bg-white/[0.12] text-text-primary border border-border-primary disabled:opacity-50"
        >
          {running ? "Scoring…" : "Run scoring job"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-signal-red/40 bg-signal-red/10 p-3 text-[12px] text-signal-red">
          {error}
        </div>
      )}

      {nSignals === 0 ? (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-6">
          <p className="text-text-secondary">No signals scored yet.</p>
          <p className="text-[12px] text-text-tertiary mt-2">
            Trade ideas must age at least 1 day before they can be scored. Generate
            a memo with trade ideas, wait a day, then click "Run scoring job" above.
          </p>
        </div>
      ) : (
        <>
          {/* Headline stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat
              label="Signals Scored"
              value={String(nSignals)}
              help="Trade ideas scored against realized prices"
            />
            <Stat
              label="Hit Rate 5d"
              value={fmtPct(summary?.hit_rate_5d)}
              help="% of signals with direction-correct realized return at 5 trading days"
              color={
                (summary?.hit_rate_5d ?? 0) >= 55
                  ? "text-signal-green"
                  : (summary?.hit_rate_5d ?? 0) >= 45
                  ? "text-text-primary"
                  : "text-signal-red"
              }
            />
            <Stat
              label="IC 5d"
              value={fmtNum(summary?.ic_5d, 3)}
              help="Information Coefficient at 5d — correlation of (conviction × direction) with realized return. Above 0.05 is publishable; above 0.10 is strong."
              color={
                (summary?.ic_5d ?? 0) >= 0.1
                  ? "text-signal-green"
                  : (summary?.ic_5d ?? 0) >= 0.05
                  ? "text-text-primary"
                  : "text-text-secondary"
              }
            />
            <Stat
              label="IC 20d"
              value={fmtNum(summary?.ic_20d, 3)}
              help="Information Coefficient at 20d — measures whether higher-conviction calls produce larger realized moves"
              color={
                (summary?.ic_20d ?? 0) >= 0.1
                  ? "text-signal-green"
                  : (summary?.ic_20d ?? 0) >= 0.05
                  ? "text-text-primary"
                  : "text-text-secondary"
              }
            />
          </div>

          {!stable && (
            <div className="rounded-lg border border-signal-yellow/40 bg-signal-yellow/10 p-3 text-[12px] text-signal-yellow">
              Insufficient history — {nSignals} signal{nSignals === 1 ? "" : "s"} scored,
              need {STABLE_IC_MIN_SIGNALS}+ for stable IC. Numbers shown but interpret with care.
            </div>
          )}

          {/* Alpha decay panel */}
          <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
            <h2 className="text-[13px] font-medium text-text-primary mb-1">
              Alpha Decay
            </h2>
            <p className="text-[11px] text-text-tertiary mb-4">
              Hit rate and average return at each horizon. Decay (lower numbers at longer horizons)
              suggests signals fade quickly — better suited for short-term tactical trades. Stable or
              rising numbers suggest the alpha persists.
            </p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={decayData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                  <XAxis dataKey="horizon" stroke="#666" style={{ fontSize: 11 }} />
                  <YAxis
                    yAxisId="left"
                    stroke="#666"
                    style={{ fontSize: 11 }}
                    label={{ value: "Hit rate %", angle: -90, position: "insideLeft", style: { fontSize: 10, fill: "#666" } }}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    stroke="#666"
                    style={{ fontSize: 11 }}
                    label={{ value: "Avg return %", angle: 90, position: "insideRight", style: { fontSize: 10, fill: "#666" } }}
                  />
                  <ReferenceLine yAxisId="left" y={50} stroke="#444" strokeDasharray="3 3" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#111", border: "1px solid #333", fontSize: 12 }}
                    labelStyle={{ color: "#aaa" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="hit_rate"
                    name="Hit rate %"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="avg_return_pct"
                    name="Avg return %"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Conviction bucket panel */}
          <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
            <h2 className="text-[13px] font-medium text-text-primary mb-1">
              Hit Rate by Conviction
            </h2>
            <p className="text-[11px] text-text-tertiary mb-4">
              A working signal should show monotonic improvement: high-conviction
              calls hit more often than medium, which hit more often than low. Flat or
              inverted bars are a calibration problem.
            </p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={convictionData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                  <XAxis dataKey="bucket" stroke="#666" style={{ fontSize: 11 }} />
                  <YAxis
                    stroke="#666"
                    style={{ fontSize: 11 }}
                    domain={[0, 100]}
                    label={{ value: "Hit rate 5d %", angle: -90, position: "insideLeft", style: { fontSize: 10, fill: "#666" } }}
                  />
                  <ReferenceLine y={50} stroke="#444" strokeDasharray="3 3" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#111", border: "1px solid #333", fontSize: 12 }}
                    labelStyle={{ color: "#aaa" }}
                    formatter={(value, name) => {
                      const n = typeof value === "number" ? value : Number(value);
                      if (Number.isFinite(n)) {
                        return [
                          name === "avg_return_5d_pct" ? `${n.toFixed(2)}%` : `${n.toFixed(1)}%`,
                          name === "hit_rate_5d" ? "Hit rate 5d" : "Avg return 5d",
                        ] as [string, string];
                      }
                      return [String(value ?? "—"), String(name ?? "")];
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="hit_rate_5d" name="Hit rate 5d %" fill="#10b981" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-3 gap-3 mt-3 text-[11px]">
              {convictionData.map((b) => (
                <div key={b.bucket} className="rounded-lg border border-border-primary bg-bg-primary p-2">
                  <p className="text-text-quaternary uppercase tracking-wider mb-1">{b.bucket}</p>
                  <p className="font-mono text-text-secondary">{b.count} signals</p>
                  <p className={`font-mono ${returnColor(b.avg_return_5d_pct === null ? null : b.avg_return_5d_pct / 100)}`}>
                    {b.avg_return_5d_pct !== null
                      ? `${b.avg_return_5d_pct.toFixed(2)}% avg`
                      : "—"}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Monthly hit rate over time */}
          {monthlyData.length > 1 && (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
              <h2 className="text-[13px] font-medium text-text-primary mb-1">
                Hit Rate Over Time
              </h2>
              <p className="text-[11px] text-text-tertiary mb-4">
                Monthly 5d hit rate. Watch for regime breaks — a sudden drop suggests
                the model's edge has degraded and warrants re-evaluation.
              </p>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                    <XAxis dataKey="month" stroke="#666" style={{ fontSize: 11 }} />
                    <YAxis stroke="#666" style={{ fontSize: 11 }} domain={[0, 100]} />
                    <ReferenceLine y={50} stroke="#444" strokeDasharray="3 3" />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#111", border: "1px solid #333", fontSize: 12 }}
                      labelStyle={{ color: "#aaa" }}
                      formatter={(value) => {
                        const n = typeof value === "number" ? value : Number(value);
                        if (Number.isFinite(n)) return [`${n.toFixed(1)}%`, "Hit rate 5d"] as [string, string];
                        return [String(value ?? "—"), "Hit rate 5d"];
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="hit_rate_5d"
                      stroke="#10b981"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Top winners + losers */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
              <h2 className="text-[13px] font-medium text-text-primary mb-3">Top Winners (20d)</h2>
              {summary && summary.top_winners.length === 0 ? (
                <p className="text-[12px] text-text-tertiary">No closed signals yet.</p>
              ) : (
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="text-text-quaternary text-left">
                      <th className="font-normal pb-2">Ticker</th>
                      <th className="font-normal pb-2">Dir</th>
                      <th className="font-normal pb-2 text-right">Conv</th>
                      <th className="font-normal pb-2 text-right">20d Return</th>
                    </tr>
                  </thead>
                  <tbody className="text-text-secondary">
                    {summary?.top_winners.map((w, i) => (
                      <tr key={`${w.ticker}-${i}`} className="border-t border-border-primary">
                        <td className="py-1.5 font-medium text-text-primary">{w.ticker}</td>
                        <td className="py-1.5">{w.direction}</td>
                        <td className="py-1.5 text-right font-mono">{w.conviction}</td>
                        <td className={`py-1.5 text-right font-mono ${returnColor(w.return_20d)}`}>
                          {fmtReturn(w.return_20d)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
              <h2 className="text-[13px] font-medium text-text-primary mb-3">Top Losers (20d)</h2>
              {summary && summary.top_losers.length === 0 ? (
                <p className="text-[12px] text-text-tertiary">No drawdowns yet.</p>
              ) : (
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="text-text-quaternary text-left">
                      <th className="font-normal pb-2">Ticker</th>
                      <th className="font-normal pb-2">Dir</th>
                      <th className="font-normal pb-2 text-right">Conv</th>
                      <th className="font-normal pb-2 text-right">20d Return</th>
                    </tr>
                  </thead>
                  <tbody className="text-text-secondary">
                    {summary?.top_losers.map((l, i) => (
                      <tr key={`${l.ticker}-${i}`} className="border-t border-border-primary">
                        <td className="py-1.5 font-medium text-text-primary">{l.ticker}</td>
                        <td className="py-1.5">{l.direction}</td>
                        <td className="py-1.5 text-right font-mono">{l.conviction}</td>
                        <td className={`py-1.5 text-right font-mono ${returnColor(l.return_20d)}`}>
                          {fmtReturn(l.return_20d)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* ─────────────────── Portfolio Attribution ─────────────────── */}
          {attribution && !attribution.error && attribution.decomposition && (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
              <h2 className="text-[13px] font-medium text-text-primary mb-1">
                Portfolio Attribution
              </h2>
              <p className="text-[11px] text-text-tertiary mb-4">
                Decomposing actual book returns into alpha (idiosyncratic) vs
                beta × market (factor exposure) vs residual. Run on your open
                positions over the available history window.
              </p>

              <div className="grid grid-cols-3 gap-3 mb-4">
                <Stat
                  label="Portfolio Return"
                  value={
                    attribution.period_return_pct !== undefined
                      ? `${attribution.period_return_pct >= 0 ? "+" : ""}${attribution.period_return_pct.toFixed(2)}%`
                      : null
                  }
                  color={
                    attribution.period_return_pct !== undefined && attribution.period_return_pct >= 0
                      ? "text-signal-green"
                      : "text-signal-red"
                  }
                />
                <Stat
                  label="SPY Benchmark"
                  value={
                    attribution.benchmark_return_pct !== undefined
                      ? `${attribution.benchmark_return_pct >= 0 ? "+" : ""}${attribution.benchmark_return_pct.toFixed(2)}%`
                      : null
                  }
                />
                <Stat
                  label="R-Squared"
                  value={
                    attribution.factor_loadings?.r_squared !== null && attribution.factor_loadings?.r_squared !== undefined
                      ? attribution.factor_loadings.r_squared.toFixed(2)
                      : null
                  }
                  help="% of portfolio return variance explained by market beta"
                />
              </div>

              <div className="space-y-2 mb-4">
                {[
                  {
                    label: "Alpha (skill)",
                    value: attribution.decomposition.alpha_pct,
                    bar: (attribution.decomposition.alpha_pct ?? 0) >= 0 ? "bg-signal-green" : "bg-signal-red",
                    color: (attribution.decomposition.alpha_pct ?? 0) >= 0 ? "text-signal-green" : "text-signal-red",
                  },
                  {
                    label: "Beta × Market",
                    value: attribution.decomposition.beta_contribution_pct,
                    bar: attribution.decomposition.beta_contribution_pct >= 0 ? "bg-accent" : "bg-signal-red",
                    color: attribution.decomposition.beta_contribution_pct >= 0 ? "text-accent" : "text-signal-red",
                  },
                  {
                    label: "Residual (noise)",
                    value: attribution.decomposition.residual_pct,
                    bar: "bg-signal-yellow",
                    color: "text-signal-yellow",
                  },
                ].map((row) => (
                  <div key={row.label} className="flex items-center gap-3">
                    <span className="text-[11px] text-text-secondary w-32">{row.label}</span>
                    <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden">
                      <div
                        className={`h-full rounded-full ${row.bar}`}
                        style={{ width: `${Math.min(Math.abs(row.value ?? 0) * 5, 100)}%` }}
                      />
                    </div>
                    <span className={`text-[12px] font-mono w-16 text-right ${row.color}`}>
                      {row.value !== null && row.value !== undefined
                        ? `${row.value >= 0 ? "+" : ""}${row.value.toFixed(2)}%`
                        : "—"}
                    </span>
                  </div>
                ))}
              </div>

              {attribution.factor_loadings && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-3 border-t border-border-primary">
                  <div>
                    <p className="text-[10px] text-text-quaternary uppercase tracking-wider">Alpha (ann.)</p>
                    <p
                      className={`text-[13px] font-mono ${
                        (attribution.factor_loadings.alpha ?? 0) >= 0 ? "text-signal-green" : "text-signal-red"
                      }`}
                    >
                      {attribution.factor_loadings.alpha !== null && attribution.factor_loadings.alpha !== undefined
                        ? `${attribution.factor_loadings.alpha >= 0 ? "+" : ""}${attribution.factor_loadings.alpha.toFixed(2)}%`
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-quaternary uppercase tracking-wider">Beta vs SPY</p>
                    <p className="text-[13px] font-mono text-text-primary">
                      {attribution.factor_loadings.beta !== null && attribution.factor_loadings.beta !== undefined
                        ? attribution.factor_loadings.beta.toFixed(3)
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-quaternary uppercase tracking-wider">R²</p>
                    <p className="text-[13px] font-mono text-text-primary">
                      {attribution.factor_loadings.r_squared !== null && attribution.factor_loadings.r_squared !== undefined
                        ? attribution.factor_loadings.r_squared.toFixed(3)
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-quaternary uppercase tracking-wider">Residual Vol</p>
                    <p className="text-[13px] font-mono text-text-primary">
                      {attribution.factor_loadings.residual_vol !== null && attribution.factor_loadings.residual_vol !== undefined
                        ? `${attribution.factor_loadings.residual_vol.toFixed(2)}%`
                        : "—"}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {attribution?.error && (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
              <h2 className="text-[13px] font-medium text-text-primary mb-1">
                Portfolio Attribution
              </h2>
              <p className="text-[12px] text-text-tertiary">
                {attribution.error}. Attribution requires open trades with 3+ months of price
                history per ticker.
              </p>
            </div>
          )}

          {/* ─────────────────── Factor Exposure ─────────────────── */}
          <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
            <div className="flex items-baseline justify-between mb-1">
              <h2 className="text-[13px] font-medium text-text-primary">
                Factor Exposure
              </h2>
              <div className="flex items-center gap-2">
                <div className="flex rounded-lg border border-border-primary overflow-hidden">
                  <button
                    onClick={() => setFactorModel("single")}
                    className={`px-2.5 py-1 text-[11px] font-medium ${
                      factorModel === "single"
                        ? "bg-white text-bg-primary"
                        : "text-text-tertiary hover:text-text-primary"
                    }`}
                  >
                    Single-factor
                  </button>
                  <button
                    onClick={() => setFactorModel("ff5_mom")}
                    className={`px-2.5 py-1 text-[11px] font-medium ${
                      factorModel === "ff5_mom"
                        ? "bg-white text-bg-primary"
                        : "text-text-tertiary hover:text-text-primary"
                    }`}
                  >
                    FF5 + Mom
                  </button>
                </div>
                <button
                  onClick={() => loadFactors(factorModel)}
                  disabled={factorLoading || openTickers.length === 0}
                  className="rounded-lg px-3 py-1 text-[11px] font-medium bg-white/[0.07] hover:bg-white/[0.12] text-text-primary border border-border-primary disabled:opacity-50"
                >
                  {factorLoading ? "Computing…" : "Run"}
                </button>
              </div>
            </div>
            <p className="text-[11px] text-text-tertiary mb-3">
              Factor regression on your open positions ({openTickers.length} tickers).
              FF5 + Momentum uses ETF proxies (IWM, IWD/IWF, QUAL, USMV, MTUM).
              {openTickers.length === 0 && " — Open at least one position to enable."}
            </p>

            {factors && (() => {
              const usingMulti = !!factors.multi_factor && !factors.multi_factor.error;
              const view = usingMulti
                ? {
                    alpha: factors.multi_factor!.alpha,
                    beta: null as number | null,
                    r_squared: factors.multi_factor!.r_squared,
                    factor_betas: factors.multi_factor!.factor_betas,
                    factor_tstats: factors.multi_factor!.factor_tstats,
                    residual_vol: factors.multi_factor!.residual_vol,
                    alpha_pvalue: factors.multi_factor!.alpha_pvalue,
                    alpha_significant: factors.multi_factor!.alpha_significant_at_5pct,
                    n_observations: factors.multi_factor!.n_observations,
                    model_label: factors.multi_factor!.model || "FF5 + Momentum",
                    multicollinearity: factors.multi_factor!.multicollinearity_flag,
                    high_vif: factors.multi_factor!.high_vif_factors,
                  }
                : {
                    alpha: factors.alpha,
                    beta: factors.beta,
                    r_squared: factors.r_squared,
                    factor_betas: factors.factor_betas,
                    factor_tstats: undefined as Record<string, number> | undefined,
                    residual_vol: factors.residual_vol,
                    alpha_pvalue: factors.alpha_pvalue,
                    alpha_significant: factors.alpha_significant_at_5pct,
                    n_observations: factors.n_observations,
                    model_label: "Single-factor (CAPM)",
                    multicollinearity: false,
                    high_vif: undefined as string[] | undefined,
                  };
              return (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-text-quaternary uppercase tracking-wider">Model</span>
                      <span className="text-[11px] font-mono text-text-primary">{view.model_label}</span>
                      {view.n_observations && (
                        <span className="text-[10px] text-text-quaternary">n={view.n_observations}</span>
                      )}
                    </div>
                    {view.alpha_pvalue !== null && view.alpha_pvalue !== undefined && (
                      <div
                        className={`text-[10px] font-medium px-2 py-0.5 rounded ${
                          view.alpha_significant
                            ? "bg-signal-green/10 text-signal-green border border-signal-green/30"
                            : "bg-signal-yellow/10 text-signal-yellow border border-signal-yellow/30"
                        }`}
                      >
                        {view.alpha_significant ? "Alpha significant" : "Alpha not significant"} · p={view.alpha_pvalue.toFixed(3)}
                      </div>
                    )}
                  </div>

                  <div className={`grid gap-3 ${usingMulti ? "grid-cols-2" : "grid-cols-3"}`}>
                    <Stat
                      label="Alpha (ann.)"
                      value={
                        view.alpha !== null && view.alpha !== undefined
                          ? `${Number(view.alpha) >= 0 ? "+" : ""}${Number(view.alpha).toFixed(2)}%`
                          : null
                      }
                      color={Number(view.alpha ?? 0) >= 0 ? "text-signal-green" : "text-signal-red"}
                    />
                    {!usingMulti && (
                      <Stat
                        label="Beta"
                        value={view.beta !== null && view.beta !== undefined ? Number(view.beta).toFixed(3) : null}
                      />
                    )}
                    <Stat
                      label="R-Squared"
                      value={view.r_squared !== null && view.r_squared !== undefined ? Number(view.r_squared).toFixed(3) : null}
                    />
                  </div>

                  {view.factor_betas && (
                    <div>
                      <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-2">
                        Factor Exposures
                      </p>
                      <div className="space-y-1.5">
                        {Object.entries(view.factor_betas).map(([factor, beta]) => {
                          const t = view.factor_tstats?.[factor];
                          const sig = t !== null && t !== undefined && Math.abs(t) >= 1.96;
                          return (
                            <div key={factor} className="flex items-center gap-3">
                              <span className="text-[11px] text-text-secondary w-28 capitalize">
                                {factor.replace(/_/g, " ")}
                              </span>
                              <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${Number(beta) >= 0 ? "bg-accent" : "bg-signal-red"}`}
                                  style={{
                                    width: `${Math.min(Math.abs(Number(beta)) * 50, 100)}%`,
                                    marginLeft: Number(beta) < 0 ? "auto" : 0,
                                  }}
                                />
                              </div>
                              <span className="text-[11px] font-mono text-text-primary w-14 text-right">
                                {beta !== null && beta !== undefined ? Number(beta).toFixed(3) : "—"}
                              </span>
                              {t !== null && t !== undefined && (
                                <span
                                  className={`text-[10px] font-mono w-14 text-right ${
                                    sig ? "text-signal-green" : "text-text-quaternary"
                                  }`}
                                >
                                  t={t.toFixed(2)}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <p className="text-[10px] text-text-quaternary mt-2">
                        |t| ≥ 1.96 indicates significance at 5%.
                      </p>
                    </div>
                  )}

                  {view.multicollinearity && view.high_vif && view.high_vif.length > 0 && (
                    <div className="rounded-lg border border-signal-yellow/40 bg-signal-yellow/10 p-2 text-[11px] text-signal-yellow">
                      Multicollinearity flagged on: {view.high_vif.join(", ")} (VIF &gt; 10). Interpret these betas carefully.
                    </div>
                  )}

                  {view.residual_vol !== null && view.residual_vol !== undefined && (
                    <p className="text-[11px] text-text-quaternary">
                      Residual vol (idiosyncratic risk):{" "}
                      <span className="font-mono text-text-primary">
                        {Number(view.residual_vol).toFixed(2)}%
                      </span>
                    </p>
                  )}
                </div>
              );
            })()}

            {!factors && openTickers.length > 0 && (
              <p className="text-[11px] text-text-tertiary">Click Run to compute.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
