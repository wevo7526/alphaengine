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
import { TerminalHeader } from "@/components/TerminalHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { StatPanel } from "@/components/StatPanel";
import { StatusPill } from "@/components/StatusPill";

const STABLE_IC_MIN_SIGNALS = 20;

// Design-token Recharts colors so charts match the rest of the platform.
const CHART_GRID = "#27272a"; // border-primary
const CHART_AXIS = "#71717a"; // text-tertiary
const CHART_REF = "#3f3f46"; // between border-primary and text-quaternary

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

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

function fmtReturn(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function returnColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-text-secondary";
  if (v > 0) return "text-signal-green";
  if (v < 0) return "text-signal-red";
  return "text-text-secondary";
}

function aggregateHitRateByMonth(signals: SignalScore[]) {
  const buckets: Record<string, { hits: number; total: number; sum_ret: number; n_ret: number }> = {};
  for (const s of signals) {
    if (!s.signal_date) continue;
    const month = s.signal_date.slice(0, 7);
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
      <div className="p-8 text-text-secondary font-mono text-[12px]">
        Loading scorecard…
      </div>
    );
  }

  const nSignals = summary?.signals ?? 0;
  const stable = nSignals >= STABLE_IC_MIN_SIGNALS;

  const convictionData = summary
    ? Object.entries(summary.by_conviction).map(([name, b]) => ({
        bucket: name,
        count: b.count,
        hit_rate_5d: b.hit_rate_5d ?? null,
        avg_return_5d_pct: b.avg_return_5d !== null && b.avg_return_5d !== undefined
          ? b.avg_return_5d * 100
          : null,
      }))
    : [];

  const decayData = summary
    ? [
        { horizon: "1d", hit_rate: summary.hit_rate_1d ?? null,
          avg_return_pct: summary.avg_return_1d !== null && summary.avg_return_1d !== undefined ? summary.avg_return_1d * 100 : null },
        { horizon: "5d", hit_rate: summary.hit_rate_5d ?? null,
          avg_return_pct: summary.avg_return_5d !== null && summary.avg_return_5d !== undefined ? summary.avg_return_5d * 100 : null },
        { horizon: "20d", hit_rate: summary.hit_rate_20d ?? null,
          avg_return_pct: summary.avg_return_20d !== null && summary.avg_return_20d !== undefined ? summary.avg_return_20d * 100 : null },
      ]
    : [];

  const monthlyData = aggregateHitRateByMonth(signals);

  return (
    <div className="p-8 max-w-[1280px] mx-auto space-y-6">
      <TerminalHeader
        eyebrow="TRACK RECORD"
        title="The system grading itself"
        sub="Every past trade idea scored at 1d / 5d / 20d against realized prices."
        meta={
          <button
            onClick={runScoring}
            disabled={running}
            className="px-2.5 py-1 rounded-md bg-white text-bg-primary text-[10px] font-mono font-semibold tracking-wider hover:bg-zinc-200 disabled:opacity-30 transition-colors"
          >
            {running ? "SCORING…" : "RUN SCORING JOB"}
          </button>
        }
      />

      {error && (
        <div className="rounded-md border border-signal-red/40 bg-signal-red/10 p-3 text-[12px] text-signal-red">
          {error}
        </div>
      )}

      {nSignals === 0 ? (
        <TerminalPanel label="SCORECARD" status="EMPTY">
          <div className="text-center py-4">
            <p className="text-[13px] text-text-secondary mb-2">No signals scored yet.</p>
            <p className="text-[12px] text-text-tertiary max-w-md mx-auto">
              Trade ideas must age at least 1 day before they can be scored. Generate
              a memo with trade ideas, wait a day, then click RUN SCORING JOB above.
            </p>
          </div>
        </TerminalPanel>
      ) : (
        <>
          {/* Headline 4-stat strip */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden">
            <StatPanel
              label="SIGNALS SCORED"
              value={nSignals}
              sub="Scored against realized prices"
            />
            <StatPanel
              label="HIT RATE 5D"
              value={fmtPct(summary?.hit_rate_5d)}
              sub="Direction-correct at 5 days"
              tone={
                (summary?.hit_rate_5d ?? 0) >= 55 ? "green"
                : (summary?.hit_rate_5d ?? 0) >= 45 ? "default"
                : "red"
              }
            />
            <StatPanel
              label="IC 5D"
              value={fmtNum(summary?.ic_5d, 3)}
              sub="Above 0.05 publishable"
              tone={
                (summary?.ic_5d ?? 0) >= 0.1 ? "green"
                : (summary?.ic_5d ?? 0) >= 0.05 ? "default"
                : "default"
              }
            />
            <StatPanel
              label="IC 20D"
              value={fmtNum(summary?.ic_20d, 3)}
              sub="Conviction vs realized"
              tone={
                (summary?.ic_20d ?? 0) >= 0.1 ? "green"
                : (summary?.ic_20d ?? 0) >= 0.05 ? "default"
                : "default"
              }
            />
          </div>

          {!stable && (
            <div className="rounded-md border border-signal-yellow/40 bg-signal-yellow/10 p-3 text-[12px] text-signal-yellow">
              Insufficient history — {nSignals} signal{nSignals === 1 ? "" : "s"} scored,
              need {STABLE_IC_MIN_SIGNALS}+ for stable IC. Numbers shown but interpret with care.
            </div>
          )}

          {/* ─── SIGNAL QUALITY: Alpha Decay + Conviction Buckets ─── */}
          <TerminalPanel label="SIGNAL QUALITY" status="DECAY · CONVICTION">
            <div className="grid lg:grid-cols-2 gap-6">
              <div>
                <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                  ALPHA DECAY
                </p>
                <p className="text-[11px] text-text-tertiary mb-3 leading-relaxed">
                  Hit rate and average return at each horizon. Decay across horizons suggests
                  signals fade quickly. Stable or rising numbers suggest the alpha persists.
                </p>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={decayData}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                      <XAxis dataKey="horizon" stroke={CHART_AXIS} style={{ fontSize: 11 }} />
                      <YAxis yAxisId="left" stroke={CHART_AXIS} style={{ fontSize: 11 }}
                        label={{ value: "Hit %", angle: -90, position: "insideLeft", style: { fontSize: 10, fill: CHART_AXIS } }}
                      />
                      <YAxis yAxisId="right" orientation="right" stroke={CHART_AXIS} style={{ fontSize: 11 }}
                        label={{ value: "Return %", angle: 90, position: "insideRight", style: { fontSize: 10, fill: CHART_AXIS } }}
                      />
                      <ReferenceLine yAxisId="left" y={50} stroke={CHART_REF} strokeDasharray="3 3" />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a", fontSize: 12, borderRadius: 6 }} labelStyle={{ color: "#a1a1aa" }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line yAxisId="left" type="monotone" dataKey="hit_rate" name="Hit %" stroke="#10b981" strokeWidth={2} dot={{ r: 4 }} />
                      <Line yAxisId="right" type="monotone" dataKey="avg_return_pct" name="Return %" stroke="#3b82f6" strokeWidth={2} dot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div>
                <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                  HIT RATE BY CONVICTION
                </p>
                <p className="text-[11px] text-text-tertiary mb-3 leading-relaxed">
                  A working signal shows monotonic improvement: high-conviction calls hit
                  more often than medium, which hit more often than low.
                </p>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={convictionData}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                      <XAxis dataKey="bucket" stroke={CHART_AXIS} style={{ fontSize: 11 }} />
                      <YAxis stroke={CHART_AXIS} style={{ fontSize: 11 }} domain={[0, 100]} />
                      <ReferenceLine y={50} stroke={CHART_REF} strokeDasharray="3 3" />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a", fontSize: 12, borderRadius: 6 }} labelStyle={{ color: "#a1a1aa" }}
                        formatter={(value, name) => {
                          const n = typeof value === "number" ? value : Number(value);
                          if (Number.isFinite(n)) {
                            return [
                              name === "avg_return_5d_pct" ? `${n.toFixed(2)}%` : `${n.toFixed(1)}%`,
                              name === "hit_rate_5d" ? "Hit 5d" : "Return 5d",
                            ] as [string, string];
                          }
                          return [String(value ?? "—"), String(name ?? "")];
                        }}
                      />
                      <Bar dataKey="hit_rate_5d" name="Hit 5d %" fill="#10b981" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="grid grid-cols-3 gap-2 mt-3 text-[11px]">
                  {convictionData.map((b) => (
                    <div key={b.bucket} className="rounded-md border border-border-primary/60 bg-bg-primary/40 p-2">
                      <p className="text-text-quaternary uppercase tracking-wider text-[9px] font-mono">{b.bucket}</p>
                      <p className="font-mono text-text-secondary tabular-nums">{b.count}</p>
                      <p className={`font-mono tabular-nums ${returnColor(b.avg_return_5d_pct === null ? null : b.avg_return_5d_pct / 100)}`}>
                        {b.avg_return_5d_pct !== null ? `${b.avg_return_5d_pct.toFixed(2)}%` : "—"}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </TerminalPanel>

          {/* ─── TIMELINE: Monthly Hit Rate + Top Winners/Losers ─── */}
          <TerminalPanel label="TIMELINE" status="MONTHLY · WINNERS · LOSERS">
            {monthlyData.length > 1 && (
              <div className="mb-6">
                <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                  HIT RATE OVER TIME
                </p>
                <p className="text-[11px] text-text-tertiary mb-3 leading-relaxed">
                  Monthly 5d hit rate. Watch for regime breaks — a sudden drop suggests
                  the model&apos;s edge has degraded and warrants re-evaluation.
                </p>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={monthlyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                      <XAxis dataKey="month" stroke={CHART_AXIS} style={{ fontSize: 11 }} />
                      <YAxis stroke={CHART_AXIS} style={{ fontSize: 11 }} domain={[0, 100]} />
                      <ReferenceLine y={50} stroke={CHART_REF} strokeDasharray="3 3" />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a", fontSize: 12, borderRadius: 6 }} labelStyle={{ color: "#a1a1aa" }}
                        formatter={(value) => {
                          const n = typeof value === "number" ? value : Number(value);
                          if (Number.isFinite(n)) return [`${n.toFixed(1)}%`, "Hit 5d"] as [string, string];
                          return [String(value ?? "—"), "Hit 5d"];
                        }}
                      />
                      <Line type="monotone" dataKey="hit_rate_5d" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div>
                <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                  TOP WINNERS (20D)
                </p>
                {summary && summary.top_winners.length === 0 ? (
                  <p className="text-[12px] text-text-tertiary">No closed signals yet.</p>
                ) : (
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="text-text-quaternary text-left">
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2">Ticker</th>
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2">Dir</th>
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2 text-right">Conv</th>
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2 text-right">20d</th>
                      </tr>
                    </thead>
                    <tbody className="text-text-secondary">
                      {summary?.top_winners.map((w, i) => (
                        <tr key={`${w.ticker}-${i}`} className="border-t border-border-primary/40">
                          <td className="py-1.5 font-mono font-semibold text-text-primary">{w.ticker}</td>
                          <td className="py-1.5 text-[11px]">{w.direction}</td>
                          <td className="py-1.5 text-right font-mono tabular-nums">{w.conviction}</td>
                          <td className={`py-1.5 text-right font-mono tabular-nums ${returnColor(w.return_20d)}`}>
                            {fmtReturn(w.return_20d)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div>
                <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                  TOP LOSERS (20D)
                </p>
                {summary && summary.top_losers.length === 0 ? (
                  <p className="text-[12px] text-text-tertiary">No drawdowns yet.</p>
                ) : (
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="text-text-quaternary text-left">
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2">Ticker</th>
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2">Dir</th>
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2 text-right">Conv</th>
                        <th className="font-mono text-[9px] uppercase tracking-[0.18em] pb-2 text-right">20d</th>
                      </tr>
                    </thead>
                    <tbody className="text-text-secondary">
                      {summary?.top_losers.map((l, i) => (
                        <tr key={`${l.ticker}-${i}`} className="border-t border-border-primary/40">
                          <td className="py-1.5 font-mono font-semibold text-text-primary">{l.ticker}</td>
                          <td className="py-1.5 text-[11px]">{l.direction}</td>
                          <td className="py-1.5 text-right font-mono tabular-nums">{l.conviction}</td>
                          <td className={`py-1.5 text-right font-mono tabular-nums ${returnColor(l.return_20d)}`}>
                            {fmtReturn(l.return_20d)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </TerminalPanel>

          {/* ─── ATTRIBUTION: Portfolio Attribution + Factor Exposure ─── */}
          {(attribution?.decomposition || factors || openTickers.length > 0) && (
            <TerminalPanel label="ATTRIBUTION" status="DECOMPOSITION · FACTORS">
              {/* Portfolio Attribution */}
              {attribution && !attribution.error && attribution.decomposition && (
                <div className="mb-6">
                  <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                    PORTFOLIO ATTRIBUTION
                  </p>
                  <p className="text-[11px] text-text-tertiary mb-4 leading-relaxed">
                    Decomposing actual book returns into alpha (idiosyncratic) vs
                    beta × market (factor exposure) vs residual.
                  </p>

                  <div className="grid grid-cols-3 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden mb-4">
                    <StatPanel
                      label="PORTFOLIO RETURN"
                      value={
                        attribution.period_return_pct !== undefined
                          ? `${attribution.period_return_pct >= 0 ? "+" : ""}${attribution.period_return_pct.toFixed(2)}%`
                          : "—"
                      }
                      tone={
                        attribution.period_return_pct !== undefined && attribution.period_return_pct >= 0
                          ? "green"
                          : "red"
                      }
                    />
                    <StatPanel
                      label="SPY BENCHMARK"
                      value={
                        attribution.benchmark_return_pct !== undefined
                          ? `${attribution.benchmark_return_pct >= 0 ? "+" : ""}${attribution.benchmark_return_pct.toFixed(2)}%`
                          : "—"
                      }
                    />
                    <StatPanel
                      label="R-SQUARED"
                      value={
                        attribution.factor_loadings?.r_squared !== null && attribution.factor_loadings?.r_squared !== undefined
                          ? attribution.factor_loadings.r_squared.toFixed(2)
                          : "—"
                      }
                      sub="Variance explained by β"
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
                        <span className={`text-[12px] font-mono w-16 text-right tabular-nums ${row.color}`}>
                          {row.value !== null && row.value !== undefined
                            ? `${row.value >= 0 ? "+" : ""}${row.value.toFixed(2)}%`
                            : "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {attribution?.error && (
                <p className="text-[12px] text-text-tertiary mb-4">
                  Attribution unavailable: {attribution.error}. Needs open trades with 3+ months
                  of price history per ticker.
                </p>
              )}

              {/* Factor Exposure */}
              <div className="border-t border-border-primary/40 pt-5">
                <div className="flex items-baseline justify-between mb-2 flex-wrap gap-3">
                  <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
                    FACTOR EXPOSURE
                  </p>
                  <div className="flex items-center gap-2">
                    <div className="inline-flex items-center gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden">
                      <button
                        onClick={() => setFactorModel("single")}
                        className={`px-2.5 py-1 text-[10px] font-mono tracking-wider ${
                          factorModel === "single"
                            ? "bg-bg-surface text-text-primary"
                            : "bg-bg-primary text-text-tertiary hover:text-text-secondary"
                        }`}
                      >
                        SINGLE
                      </button>
                      <button
                        onClick={() => setFactorModel("ff5_mom")}
                        className={`px-2.5 py-1 text-[10px] font-mono tracking-wider ${
                          factorModel === "ff5_mom"
                            ? "bg-bg-surface text-text-primary"
                            : "bg-bg-primary text-text-tertiary hover:text-text-secondary"
                        }`}
                      >
                        FF5 + MOM
                      </button>
                    </div>
                    <button
                      onClick={() => loadFactors(factorModel)}
                      disabled={factorLoading || openTickers.length === 0}
                      className="rounded-md px-3 py-1 text-[10px] font-mono font-semibold tracking-wider bg-white text-bg-primary hover:bg-zinc-200 disabled:opacity-30 transition-colors"
                    >
                      {factorLoading ? "COMPUTING…" : "RUN"}
                    </button>
                  </div>
                </div>
                <p className="text-[11px] text-text-tertiary mb-4 leading-relaxed">
                  Factor regression on your open positions ({openTickers.length} tickers).
                  FF5 + Momentum uses ETF proxies (IWM, IWD/IWF, QUAL, USMV, MTUM).
                  {openTickers.length === 0 && " Open at least one position to enable."}
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
                    <div className="space-y-4">
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-2 text-[10px] font-mono">
                          <span className="text-text-quaternary tracking-[0.18em] uppercase">Model</span>
                          <span className="text-text-primary">{view.model_label}</span>
                          {view.n_observations && (
                            <span className="text-text-quaternary">n={view.n_observations}</span>
                          )}
                        </div>
                        {view.alpha_pvalue !== null && view.alpha_pvalue !== undefined && (
                          <StatusPill
                            label={`${view.alpha_significant ? "ALPHA SIG" : "NOT SIG"} · p=${view.alpha_pvalue.toFixed(3)}`}
                            tone={view.alpha_significant ? "green" : "yellow"}
                          />
                        )}
                      </div>

                      <div className={`grid grid-cols-${usingMulti ? "2" : "3"} gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden`}>
                        <StatPanel
                          label="ALPHA (ANN.)"
                          value={
                            view.alpha !== null && view.alpha !== undefined
                              ? `${Number(view.alpha) >= 0 ? "+" : ""}${Number(view.alpha).toFixed(2)}%`
                              : "—"
                          }
                          tone={Number(view.alpha ?? 0) >= 0 ? "green" : "red"}
                        />
                        {!usingMulti && (
                          <StatPanel
                            label="BETA"
                            value={view.beta !== null && view.beta !== undefined ? Number(view.beta).toFixed(3) : "—"}
                          />
                        )}
                        <StatPanel
                          label="R-SQUARED"
                          value={view.r_squared !== null && view.r_squared !== undefined ? Number(view.r_squared).toFixed(3) : "—"}
                        />
                      </div>

                      {view.factor_betas && (
                        <div>
                          <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-3">
                            FACTOR LOADINGS
                          </p>
                          <div className="space-y-1.5">
                            {Object.entries(view.factor_betas).map(([factor, beta]) => {
                              const t = view.factor_tstats?.[factor];
                              const sig = t !== null && t !== undefined && Math.abs(t) >= 1.96;
                              return (
                                <div key={factor} className="flex items-center gap-3">
                                  <span className="text-[11px] text-text-secondary w-28 capitalize font-mono">
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
                                  <span className="text-[11px] font-mono text-text-primary w-14 text-right tabular-nums">
                                    {beta !== null && beta !== undefined ? Number(beta).toFixed(3) : "—"}
                                  </span>
                                  {t !== null && t !== undefined && (
                                    <span
                                      className={`text-[10px] font-mono w-14 text-right tabular-nums ${
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
                          <p className="text-[10px] font-mono text-text-quaternary mt-3">
                            |t| ≥ 1.96 indicates significance at 5%.
                          </p>
                        </div>
                      )}

                      {view.multicollinearity && view.high_vif && view.high_vif.length > 0 && (
                        <div className="rounded-md border border-signal-yellow/40 bg-signal-yellow/10 p-2 text-[11px] text-signal-yellow">
                          Multicollinearity flagged on: {view.high_vif.join(", ")} (VIF &gt; 10). Interpret these betas carefully.
                        </div>
                      )}

                      {view.residual_vol !== null && view.residual_vol !== undefined && (
                        <p className="text-[11px] font-mono text-text-quaternary">
                          Residual vol (idiosyncratic risk):{" "}
                          <span className="text-text-primary tabular-nums">
                            {Number(view.residual_vol).toFixed(2)}%
                          </span>
                        </p>
                      )}
                    </div>
                  );
                })()}

                {!factors && openTickers.length > 0 && (
                  <p className="text-[11px] text-text-tertiary">Click RUN to compute.</p>
                )}
              </div>
            </TerminalPanel>
          )}
        </>
      )}
    </div>
  );
}
