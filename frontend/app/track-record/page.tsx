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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, sigResp] = await Promise.all([
        api.scorecardSummary() as Promise<ScorecardSummary>,
        api.scorecardSignals(200) as Promise<SignalsResp>,
      ]);
      setSummary(s);
      setSignals(sigResp?.signals ?? []);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load track record";
      setError(msg);
    } finally {
      setLoading(false);
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
        </>
      )}
    </div>
  );
}
