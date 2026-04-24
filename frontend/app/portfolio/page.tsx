"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DIRECTION_STYLE } from "@/lib/types";
import type { IntelligenceMemo } from "@/lib/types";
import { ConvictionBar } from "@/components/ConvictionBar";
import { MemoPanel } from "@/components/MemoPanel";

// Removed: was evaluating at module load (SSR) and always returning localhost

interface Trade {
  id: string;
  ticker: string;
  direction: string;
  action: string;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  position_size_pct: number;
  conviction: number;
  thesis: string;
  status: string;
  realized_pnl: number | null;
  opened_at: string | null;
  closed_at: string | null;
}

interface BacktestResult {
  id: string;
  ticker: string;
  direction: string;
  conviction: number;
  thesis: string;
  evaluation: {
    current_price?: number;
    unrealized_pnl_pct?: number | null;
    hit_stop?: boolean;
    hit_target?: boolean;
    status?: string;
    error?: string;
  };
}

interface BacktestSummary {
  total: number;
  wins: number;
  losses: number;
  open: number;
  win_rate: number;
}

interface Position {
  ticker: string;
  direction: string;
  avg_entry_price: number | null;
  current_price: number | null;
  total_size_pct: number;
  unrealized_pnl_pct: number | null;
  unrealized_pnl_dollars: number | null;
  cost_basis: number | null;
  market_value: number | null;
  avg_stop_loss: number | null;
  avg_take_profit: number | null;
  weight_pct: number | null;
  trade_count: number;
  opened_at: string | null;
}

interface PositionsSummary {
  portfolio_base: number;
  total_cost_basis: number;
  total_market_value: number;
  total_unrealized_pnl: number;
  total_unrealized_pnl_pct: number;
  total_realized_pnl: number;
  total_realized_pnl_pct_avg: number;
  open_positions: number;
  closed_trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
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
  by_conviction: Record<string, { count: number; hit_rate_5d?: number | null; avg_return_5d?: number | null }>;
  top_winners?: { ticker: string; direction: string; conviction: number; return_20d: number; signal_date: string | null }[];
  top_losers?: { ticker: string; direction: string; conviction: number; return_20d: number; signal_date: string | null }[];
  error?: string;
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

export default function PortfolioPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [memos, setMemos] = useState<IntelligenceMemo[]>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);
  const [backtestSummary, setBacktestSummary] = useState<BacktestSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [backtesting, setBacktesting] = useState(false);
  const [expandedMemo, setExpandedMemo] = useState<number | null>(null);
  const [factors, setFactors] = useState<{
    alpha?: number | null; beta?: number | null; r_squared?: number | null;
    residual_vol?: number | null; factor_betas?: Record<string, number>;
  } | null>(null);
  const [tab, setTab] = useState<"positions" | "scorecard" | "attribution" | "journal" | "analyses" | "backtest" | "factors">("positions");
  const [positions, setPositions] = useState<Position[]>([]);
  const [positionsSummary, setPositionsSummary] = useState<PositionsSummary | null>(null);
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [scorecard, setScorecard] = useState<ScorecardSummary | null>(null);
  const [scorecardRunning, setScorecardRunning] = useState(false);
  const [attribution, setAttribution] = useState<AttributionData | null>(null);

  const loadPositions = () => {
    setPositionsLoading(true);
    api.positions().then((d: unknown) => {
      const data = d as { positions: Position[]; summary: PositionsSummary };
      setPositions(data.positions || []);
      setPositionsSummary(data.summary || null);
    }).catch(() => {}).finally(() => setPositionsLoading(false));
  };

  const loadScorecard = () => {
    api.scorecardSummary().then((d: unknown) => {
      setScorecard(d as ScorecardSummary);
    }).catch(() => {});
  };

  const runScoring = async () => {
    setScorecardRunning(true);
    try {
      await api.scorecardRun();
      await new Promise((r) => setTimeout(r, 500));
      loadScorecard();
    } catch {}
    setScorecardRunning(false);
  };

  const loadAttribution = () => {
    api.attribution().then((d: unknown) => {
      setAttribution(d as AttributionData);
    }).catch(() => {});
  };

  useEffect(() => {
    Promise.all([
      api.listTrades("all").then((d: unknown) => {
        setTrades((d as { trades: Trade[] }).trades);
      }).catch(() => {}),
      api.latestMemos(20).then((d: unknown) => {
        setMemos((d as { memos: IntelligenceMemo[] }).memos || []);
      }).catch(() => {}),
    ]).finally(() => setLoading(false));

    loadPositions();
    loadScorecard();
    loadAttribution();
  }, []);

  const runBacktest = () => {
    setBacktesting(true);
    api.evaluateTrades()
      .then((d: unknown) => {
        const data = d as { trades: BacktestResult[]; summary: BacktestSummary };
        setBacktestResults(data.trades);
        setBacktestSummary(data.summary);
        setBacktesting(false);
        setTab("backtest");
      })
      .catch(() => setBacktesting(false));
  };

  const openTrades = trades.filter((t) => t.status === "open");
  const closedTrades = trades.filter((t) => t.status !== "open");

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
            Portfolio
          </h1>
          <p className="text-sm text-text-tertiary">
            Trade journal, position tracking, and performance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                if (tab === "scorecard") {
                  await api.downloadPdf(api.exportScorecardUrl(), `alpha-engine-scorecard-${Date.now()}.pdf`);
                } else {
                  await api.downloadPdf(api.exportPortfolioUrl(), `alpha-engine-portfolio-${Date.now()}.pdf`);
                }
              } catch {}
            }}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-text-tertiary hover:text-text-primary hover:bg-white/[0.04] transition-colors"
          >
            Export PDF
          </button>
          <button
            onClick={runBacktest}
            disabled={backtesting}
            className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-xs font-medium hover:bg-zinc-200 transition-colors disabled:opacity-40"
          >
            {backtesting ? "Running..." : "Run Backtest"}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {[
          { key: "positions" as const, label: "Positions" },
          { key: "scorecard" as const, label: "Scorecard" },
          { key: "attribution" as const, label: "Attribution" },
          { key: "journal" as const, label: "Trade Journal" },
          { key: "analyses" as const, label: "Analyses" },
          { key: "backtest" as const, label: "Backtest" },
          { key: "factors" as const, label: "Factors" },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === t.key
                ? "bg-white/[0.07] text-text-primary"
                : "text-text-tertiary hover:text-text-secondary hover:bg-white/[0.03]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Positions Tab */}
      {tab === "positions" && (
        <>
          {positionsLoading ? (
            <p className="text-sm text-text-quaternary">Loading positions...</p>
          ) : !positionsSummary || positions.length === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-[13px] text-text-secondary mb-2">No open positions</p>
              <p className="text-xs text-text-tertiary max-w-sm mx-auto">
                Take a trade from an analysis memo, or import existing trades via the Trade Journal tab.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Summary cards */}
              <div className="grid grid-cols-4 gap-3">
                <StatCard
                  label="Total Value"
                  value={`$${positionsSummary.total_market_value.toLocaleString()}`}
                />
                <StatCard
                  label="Unrealized P&L"
                  value={`${positionsSummary.total_unrealized_pnl >= 0 ? "+" : ""}${positionsSummary.total_unrealized_pnl_pct.toFixed(2)}%`}
                  color={positionsSummary.total_unrealized_pnl >= 0 ? "text-signal-green" : "text-signal-red"}
                />
                <StatCard
                  label="Realized P&L"
                  value={`${positionsSummary.total_realized_pnl >= 0 ? "+" : ""}$${Math.abs(positionsSummary.total_realized_pnl).toLocaleString()}`}
                  color={positionsSummary.total_realized_pnl >= 0 ? "text-signal-green" : "text-signal-red"}
                />
                <StatCard
                  label="Win Rate"
                  value={positionsSummary.win_rate !== null ? `${positionsSummary.win_rate.toFixed(1)}%` : "—"}
                  color={positionsSummary.win_rate !== null && positionsSummary.win_rate >= 50 ? "text-signal-green" : positionsSummary.win_rate !== null ? "text-signal-red" : undefined}
                />
              </div>

              {/* Positions table */}
              <div className="rounded-xl border border-border-primary bg-bg-surface overflow-hidden">
                <div className="px-4 py-3 border-b border-border-primary flex items-center justify-between">
                  <div>
                    <h2 className="text-[13px] font-medium text-text-primary">Open Positions</h2>
                    <p className="text-[10px] text-text-quaternary">
                      {positionsSummary.open_positions} positions · based on ${positionsSummary.portfolio_base.toLocaleString()} portfolio
                    </p>
                  </div>
                  <button
                    onClick={loadPositions}
                    className="text-[11px] text-text-tertiary hover:text-text-secondary transition-colors"
                  >
                    Refresh
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-[10px] text-text-quaternary uppercase tracking-wider border-b border-border-primary">
                        <th className="px-4 py-2 text-left font-medium">Ticker</th>
                        <th className="px-4 py-2 text-left font-medium">Dir</th>
                        <th className="px-4 py-2 text-right font-medium">Entry</th>
                        <th className="px-4 py-2 text-right font-medium">Current</th>
                        <th className="px-4 py-2 text-right font-medium">P&L %</th>
                        <th className="px-4 py-2 text-right font-medium">P&L $</th>
                        <th className="px-4 py-2 text-right font-medium">Weight</th>
                        <th className="px-4 py-2 text-right font-medium">Stop/Target</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((p, i) => {
                        const dirLong = p.direction?.includes("bullish");
                        const pnlColor = (p.unrealized_pnl_pct ?? 0) >= 0 ? "text-signal-green" : "text-signal-red";
                        return (
                          <tr
                            key={`${p.ticker}-${p.direction}-${i}`}
                            className="border-b border-border-primary last:border-b-0 hover:bg-white/[0.02] transition-colors"
                          >
                            <td className="px-4 py-3">
                              <span className="text-[13px] font-mono font-bold text-text-primary">{p.ticker}</span>
                              {p.trade_count > 1 && (
                                <span className="ml-1.5 text-[10px] text-text-quaternary">×{p.trade_count}</span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                                dirLong ? "bg-signal-green/10 text-signal-green" : "bg-signal-red/10 text-signal-red"
                              }`}>
                                {dirLong ? "LONG" : "SHORT"}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-secondary">
                              {p.avg_entry_price !== null ? `$${p.avg_entry_price.toFixed(2)}` : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-primary">
                              {p.current_price !== null ? `$${p.current_price.toFixed(2)}` : "—"}
                            </td>
                            <td className={`px-4 py-3 text-right font-mono text-[12px] font-medium ${pnlColor}`}>
                              {p.unrealized_pnl_pct !== null ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%` : "—"}
                            </td>
                            <td className={`px-4 py-3 text-right font-mono text-[12px] ${pnlColor}`}>
                              {p.unrealized_pnl_dollars !== null
                                ? `${p.unrealized_pnl_dollars >= 0 ? "+" : ""}$${Math.abs(p.unrealized_pnl_dollars).toFixed(0)}`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-tertiary">
                              {p.weight_pct !== null ? `${p.weight_pct.toFixed(1)}%` : `${p.total_size_pct.toFixed(1)}%`}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[11px] text-text-quaternary">
                              {p.avg_stop_loss !== null ? `$${p.avg_stop_loss.toFixed(0)}` : "—"}
                              {" / "}
                              {p.avg_take_profit !== null ? `$${p.avg_take_profit.toFixed(0)}` : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Scorecard Tab */}
      {tab === "scorecard" && (
        <>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-[13px] font-medium text-text-primary mb-0.5">Signal Scorecard</h2>
              <p className="text-xs text-text-tertiary">
                How past signals performed at 1d / 5d / 20d intervals.
              </p>
            </div>
            <button
              onClick={runScoring}
              disabled={scorecardRunning}
              className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-xs font-medium hover:bg-zinc-200 transition-colors disabled:opacity-40"
            >
              {scorecardRunning ? "Scoring..." : "Score Past Signals"}
            </button>
          </div>

          {!scorecard || scorecard.signals === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-[13px] text-text-secondary mb-2">No scored signals yet</p>
              <p className="text-xs text-text-tertiary max-w-md mx-auto">
                Run an analysis, wait at least 24 hours, then click Score Past Signals.
                Signals are scored at 1, 5, and 20 trading day intervals against realized prices.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Top-line hit rates */}
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="Hit Rate (1d)"
                  value={scorecard.hit_rate_1d !== null ? `${scorecard.hit_rate_1d}%` : "—"}
                  color={scorecard.hit_rate_1d !== null && scorecard.hit_rate_1d >= 55 ? "text-signal-green" : scorecard.hit_rate_1d !== null && scorecard.hit_rate_1d < 45 ? "text-signal-red" : undefined}
                />
                <StatCard
                  label="Hit Rate (5d)"
                  value={scorecard.hit_rate_5d !== null ? `${scorecard.hit_rate_5d}%` : "—"}
                  color={scorecard.hit_rate_5d !== null && scorecard.hit_rate_5d >= 55 ? "text-signal-green" : scorecard.hit_rate_5d !== null && scorecard.hit_rate_5d < 45 ? "text-signal-red" : undefined}
                />
                <StatCard
                  label="Hit Rate (20d)"
                  value={scorecard.hit_rate_20d !== null ? `${scorecard.hit_rate_20d}%` : "—"}
                  color={scorecard.hit_rate_20d !== null && scorecard.hit_rate_20d >= 55 ? "text-signal-green" : scorecard.hit_rate_20d !== null && scorecard.hit_rate_20d < 45 ? "text-signal-red" : undefined}
                />
              </div>

              {/* Average returns */}
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="Avg Return (1d)"
                  value={scorecard.avg_return_1d !== null ? `${scorecard.avg_return_1d >= 0 ? "+" : ""}${scorecard.avg_return_1d}%` : "—"}
                  color={scorecard.avg_return_1d !== null && scorecard.avg_return_1d >= 0 ? "text-signal-green" : scorecard.avg_return_1d !== null ? "text-signal-red" : undefined}
                />
                <StatCard
                  label="Avg Return (5d)"
                  value={scorecard.avg_return_5d !== null ? `${scorecard.avg_return_5d >= 0 ? "+" : ""}${scorecard.avg_return_5d}%` : "—"}
                  color={scorecard.avg_return_5d !== null && scorecard.avg_return_5d >= 0 ? "text-signal-green" : scorecard.avg_return_5d !== null ? "text-signal-red" : undefined}
                />
                <StatCard
                  label="Avg Return (20d)"
                  value={scorecard.avg_return_20d !== null ? `${scorecard.avg_return_20d >= 0 ? "+" : ""}${scorecard.avg_return_20d}%` : "—"}
                  color={scorecard.avg_return_20d !== null && scorecard.avg_return_20d >= 0 ? "text-signal-green" : scorecard.avg_return_20d !== null ? "text-signal-red" : undefined}
                />
              </div>

              {/* Information Coefficient */}
              <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
                  Information Coefficient (conviction × direction vs return)
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-[10px] text-text-quaternary mb-0.5">IC (5d)</p>
                    <p className={`text-lg font-mono font-medium ${
                      scorecard.ic_5d !== null && scorecard.ic_5d >= 0.05 ? "text-signal-green" :
                      scorecard.ic_5d !== null && scorecard.ic_5d < 0 ? "text-signal-red" :
                      "text-text-primary"
                    }`}>
                      {scorecard.ic_5d !== null ? scorecard.ic_5d.toFixed(3) : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-quaternary mb-0.5">IC (20d)</p>
                    <p className={`text-lg font-mono font-medium ${
                      scorecard.ic_20d !== null && scorecard.ic_20d >= 0.05 ? "text-signal-green" :
                      scorecard.ic_20d !== null && scorecard.ic_20d < 0 ? "text-signal-red" :
                      "text-text-primary"
                    }`}>
                      {scorecard.ic_20d !== null ? scorecard.ic_20d.toFixed(3) : "—"}
                    </p>
                  </div>
                </div>
                <p className="text-[10px] text-text-quaternary mt-2">
                  IC &gt; 0.05 = useful · IC &gt; 0.10 = strong · IC &lt; 0 = inverse predictor
                </p>
              </div>

              {/* Per-conviction breakdown */}
              {scorecard.by_conviction && Object.keys(scorecard.by_conviction).length > 0 && (
                <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                  <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
                    By Conviction Bucket
                  </h3>
                  <div className="space-y-2">
                    {Object.entries(scorecard.by_conviction).map(([bucket, stats]) => (
                      <div key={bucket} className="flex items-center justify-between text-[12px] py-1.5 border-b border-border-primary last:border-b-0">
                        <span className="text-text-secondary capitalize">{bucket}</span>
                        <div className="flex items-center gap-4">
                          <span className="text-text-quaternary font-mono">{stats.count} signals</span>
                          {stats.hit_rate_5d !== null && stats.hit_rate_5d !== undefined && (
                            <span className={`font-mono ${
                              stats.hit_rate_5d >= 55 ? "text-signal-green" :
                              stats.hit_rate_5d < 45 ? "text-signal-red" :
                              "text-text-primary"
                            }`}>
                              hit {stats.hit_rate_5d}%
                            </span>
                          )}
                          {stats.avg_return_5d !== null && stats.avg_return_5d !== undefined && (
                            <span className={`font-mono ${stats.avg_return_5d >= 0 ? "text-signal-green" : "text-signal-red"}`}>
                              {stats.avg_return_5d >= 0 ? "+" : ""}{stats.avg_return_5d}%
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Top winners/losers */}
              {(scorecard.top_winners?.length || scorecard.top_losers?.length) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {scorecard.top_winners && scorecard.top_winners.length > 0 && (
                    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                      <h3 className="text-[11px] font-medium text-signal-green uppercase tracking-wider mb-3">
                        Top Winners (20d)
                      </h3>
                      <div className="space-y-1">
                        {scorecard.top_winners.map((w, i) => (
                          <div key={i} className="flex items-center justify-between text-[12px]">
                            <span className="font-mono font-bold text-text-primary">{w.ticker}</span>
                            <span className="text-text-quaternary text-[10px]">{w.direction} · conv {w.conviction}</span>
                            <span className="font-mono text-signal-green">+{w.return_20d}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {scorecard.top_losers && scorecard.top_losers.length > 0 && (
                    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                      <h3 className="text-[11px] font-medium text-signal-red uppercase tracking-wider mb-3">
                        Top Losers (20d)
                      </h3>
                      <div className="space-y-1">
                        {scorecard.top_losers.map((l, i) => (
                          <div key={i} className="flex items-center justify-between text-[12px]">
                            <span className="font-mono font-bold text-text-primary">{l.ticker}</span>
                            <span className="text-text-quaternary text-[10px]">{l.direction} · conv {l.conviction}</span>
                            <span className="font-mono text-signal-red">{l.return_20d}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Attribution Tab */}
      {tab === "attribution" && (
        <>
          <div className="mb-4">
            <h2 className="text-[13px] font-medium text-text-primary mb-0.5">P&L Attribution</h2>
            <p className="text-xs text-text-tertiary">
              Decompose portfolio returns into factor exposure (beta) vs alpha (stock-picking skill).
            </p>
          </div>

          {!attribution || attribution.error ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-[13px] text-text-secondary mb-2">
                {attribution?.error || "No attribution data"}
              </p>
              <p className="text-xs text-text-tertiary max-w-sm mx-auto">
                Attribution requires open trades with sufficient price history (3+ months per ticker).
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Top-line */}
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="Portfolio Return"
                  value={attribution.period_return_pct !== undefined ? `${attribution.period_return_pct >= 0 ? "+" : ""}${attribution.period_return_pct}%` : "—"}
                  color={attribution.period_return_pct !== undefined && attribution.period_return_pct >= 0 ? "text-signal-green" : "text-signal-red"}
                />
                <StatCard
                  label="SPY Benchmark"
                  value={attribution.benchmark_return_pct !== undefined ? `${attribution.benchmark_return_pct >= 0 ? "+" : ""}${attribution.benchmark_return_pct}%` : "—"}
                />
                <StatCard
                  label="R-Squared"
                  value={attribution.factor_loadings?.r_squared !== null && attribution.factor_loadings?.r_squared !== undefined ? attribution.factor_loadings.r_squared.toFixed(2) : "—"}
                />
              </div>

              {/* Decomposition */}
              {attribution.decomposition && (
                <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
                  <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-4">
                    Return Decomposition
                  </h3>
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      <span className="text-[11px] text-text-secondary w-36">Alpha (skill)</span>
                      <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden relative">
                        <div
                          className={`h-full rounded-full ${(attribution.decomposition.alpha_pct ?? 0) >= 0 ? "bg-signal-green" : "bg-signal-red"}`}
                          style={{ width: `${Math.min(Math.abs(attribution.decomposition.alpha_pct ?? 0) * 5, 100)}%` }}
                        />
                      </div>
                      <span className={`text-xs font-mono w-16 text-right ${(attribution.decomposition.alpha_pct ?? 0) >= 0 ? "text-signal-green" : "text-signal-red"}`}>
                        {attribution.decomposition.alpha_pct !== null ? `${(attribution.decomposition.alpha_pct ?? 0) >= 0 ? "+" : ""}${attribution.decomposition.alpha_pct}%` : "—"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-[11px] text-text-secondary w-36">Beta × Market</span>
                      <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden relative">
                        <div
                          className={`h-full rounded-full ${attribution.decomposition.beta_contribution_pct >= 0 ? "bg-accent" : "bg-signal-red"}`}
                          style={{ width: `${Math.min(Math.abs(attribution.decomposition.beta_contribution_pct) * 5, 100)}%` }}
                        />
                      </div>
                      <span className={`text-xs font-mono w-16 text-right ${attribution.decomposition.beta_contribution_pct >= 0 ? "text-accent" : "text-signal-red"}`}>
                        {attribution.decomposition.beta_contribution_pct >= 0 ? "+" : ""}{attribution.decomposition.beta_contribution_pct}%
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-[11px] text-text-secondary w-36">Residual (noise)</span>
                      <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden relative">
                        <div
                          className="h-full rounded-full bg-signal-yellow"
                          style={{ width: `${Math.min(Math.abs(attribution.decomposition.residual_pct) * 5, 100)}%` }}
                        />
                      </div>
                      <span className="text-xs font-mono w-16 text-right text-signal-yellow">
                        {attribution.decomposition.residual_pct >= 0 ? "+" : ""}{attribution.decomposition.residual_pct}%
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Factor loadings */}
              {attribution.factor_loadings && (
                <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
                  <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
                    Factor Loadings
                  </h3>
                  <div className="grid grid-cols-2 gap-3 text-[12px]">
                    <div>
                      <p className="text-[10px] text-text-quaternary">Alpha (annualized)</p>
                      <p className={`font-mono font-medium ${
                        (attribution.factor_loadings.alpha ?? 0) >= 0 ? "text-signal-green" : "text-signal-red"
                      }`}>
                        {attribution.factor_loadings.alpha !== null ? `${(attribution.factor_loadings.alpha ?? 0) >= 0 ? "+" : ""}${attribution.factor_loadings.alpha}%` : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-text-quaternary">Beta (vs SPY)</p>
                      <p className="font-mono font-medium text-text-primary">
                        {attribution.factor_loadings.beta !== null ? attribution.factor_loadings.beta?.toFixed(3) : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-text-quaternary">R-Squared</p>
                      <p className="font-mono font-medium text-text-primary">
                        {attribution.factor_loadings.r_squared !== null ? attribution.factor_loadings.r_squared?.toFixed(3) : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-text-quaternary">Residual Vol</p>
                      <p className="font-mono font-medium text-text-primary">
                        {attribution.factor_loadings.residual_vol !== null ? `${attribution.factor_loadings.residual_vol?.toFixed(2)}%` : "—"}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Trade Journal Tab */}
      {tab === "journal" && (
        <>
          {loading ? (
            <p className="text-sm text-text-quaternary">Loading trades...</p>
          ) : trades.length === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-[13px] text-text-secondary mb-2">No trades in your journal yet</p>
              <p className="text-xs text-text-tertiary max-w-sm mx-auto">
                Go to the Analysis page, run a query, and click "Take Trade" on any trade idea
                to start tracking positions and P&L here.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {openTrades.length > 0 && (
                <div>
                  <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
                    Open Positions ({openTrades.length})
                  </h2>
                  <div className="space-y-2">
                    {openTrades.map((t) => <TradeRow key={t.id} trade={t} onClose={() => {
                      // Refresh trades after closing
                      api.listTrades("all").then((d: unknown) => setTrades((d as { trades: Trade[] }).trades)).catch(() => {});
                    }} />)}
                  </div>
                </div>
              )}
              {closedTrades.length > 0 && (
                <div>
                  <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
                    Closed ({closedTrades.length})
                  </h2>
                  <div className="space-y-2">
                    {closedTrades.map((t) => <TradeRow key={t.id} trade={t} />)}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Analyses Tab */}
      {tab === "analyses" && (
        <>
          {memos.length === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-sm text-text-tertiary">No analyses yet. Go to Analysis to run your first query.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {memos.map((memo, i) => (
                <div key={i}>
                  <div
                    onClick={() => setExpandedMemo(expandedMemo === i ? null : i)}
                    className="rounded-xl border border-border-primary bg-bg-surface p-4 hover:border-zinc-600 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[13px] font-medium text-text-primary">{memo.title || memo.query}</span>
                      <div className="flex items-center gap-2">
                        {memo.trade_ideas && memo.trade_ideas.length > 0 && (
                          <div className="flex gap-1">
                            {memo.trade_ideas.slice(0, 5).map((ti, j) => (
                              <span key={j} className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                                ti.direction?.includes("bullish") ? "text-signal-green bg-signal-green/10" :
                                ti.direction?.includes("bearish") ? "text-signal-red bg-signal-red/10" :
                                "text-text-quaternary bg-bg-elevated"
                              }`}>
                                {ti.ticker}
                              </span>
                            ))}
                          </div>
                        )}
                        <span className="text-[10px] text-text-quaternary">
                          {memo.created_at ? new Date(memo.created_at).toLocaleDateString() : ""}
                        </span>
                        <span className="text-text-quaternary text-xs">{expandedMemo === i ? "−" : "+"}</span>
                      </div>
                    </div>
                    {expandedMemo !== i && (
                      <p className="text-xs text-text-tertiary line-clamp-2">{memo.executive_summary}</p>
                    )}
                  </div>
                  {expandedMemo === i && (
                    <div className="mt-2">
                      <MemoPanel memo={memo} onDelete={(id) => setMemos((prev) => prev.filter((m) => m.id !== id))} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Backtest Tab */}
      {tab === "backtest" && (
        <>
          {backtestSummary && (
            <div className="grid grid-cols-4 gap-3 mb-6">
              <StatCard label="Total Trades" value={String(backtestSummary.total)} />
              <StatCard label="Wins" value={String(backtestSummary.wins)} color="text-signal-green" />
              <StatCard label="Losses" value={String(backtestSummary.losses)} color="text-signal-red" />
              <StatCard label="Win Rate" value={`${backtestSummary.win_rate}%`} color={backtestSummary.win_rate >= 50 ? "text-signal-green" : "text-signal-red"} />
            </div>
          )}

          {backtestResults.length === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-sm text-text-tertiary">
                Click "Run Backtest" to evaluate open trades against current prices.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {backtestResults.map((t) => (
                <div key={t.id} className="rounded-xl border border-border-primary bg-bg-surface p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <span className="text-[15px] font-mono font-bold text-text-primary">{t.ticker}</span>
                      <span className={`text-xs ${
                        t.evaluation.status === "target_hit" ? "text-signal-green" :
                        t.evaluation.status === "stopped_out" ? "text-signal-red" :
                        "text-text-tertiary"
                      }`}>
                        {t.evaluation.status === "target_hit" ? "Target Hit" :
                         t.evaluation.status === "stopped_out" ? "Stopped Out" : "Open"}
                      </span>
                    </div>
                    {t.evaluation.current_price && (
                      <span className="text-[13px] font-mono text-text-primary">
                        ${t.evaluation.current_price.toFixed(2)}
                      </span>
                    )}
                  </div>
                  <ConvictionBar value={t.conviction} size="sm" />
                  {t.evaluation.unrealized_pnl_pct != null && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-xs text-text-quaternary">P&L:</span>
                      <span className={`text-sm font-mono font-medium ${
                        t.evaluation.unrealized_pnl_pct >= 0 ? "text-signal-green" : "text-signal-red"
                      }`}>
                        {t.evaluation.unrealized_pnl_pct > 0 ? "+" : ""}{t.evaluation.unrealized_pnl_pct}%
                      </span>
                    </div>
                  )}
                  <p className="text-xs text-text-tertiary mt-1">{t.thesis}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Factors Tab */}
      {tab === "factors" && (
        <>
          {!factors ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[13px] font-medium text-text-primary mb-0.5">Factor Exposure Analysis</p>
                  <p className="text-xs text-text-tertiary">Decompose portfolio returns into market, size, value, and momentum factors.</p>
                </div>
                <button
                  onClick={() => {
                    const tickers = [...new Set(trades.map(t => t.ticker))].slice(0, 5);
                    if (tickers.length === 0) return;
                    api.factors(tickers).then((d: unknown) => setFactors(d as typeof factors)).catch(() => {});
                  }}
                  className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-xs font-medium hover:bg-zinc-200 transition-colors"
                >
                  Compute Factors
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Alpha & Beta */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                  <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">Alpha (ann.)</p>
                  <p className={`text-lg font-mono font-medium ${
                    Number(factors.alpha || 0) >= 0 ? "text-signal-green" : "text-signal-red"
                  }`}>
                    {factors.alpha != null ? `${Number(factors.alpha) > 0 ? "+" : ""}${factors.alpha}%` : "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                  <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">Beta</p>
                  <p className="text-lg font-mono font-medium text-text-primary">
                    {factors.beta != null ? String(factors.beta) : "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
                  <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">R-Squared</p>
                  <p className="text-lg font-mono font-medium text-text-primary">
                    {factors.r_squared != null ? String(factors.r_squared) : "—"}
                  </p>
                </div>
              </div>

              {/* Factor betas if multi-factor */}
              {factors.factor_betas ? (
                <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
                  <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">Factor Exposures</h3>
                  <div className="space-y-2">
                    {Object.entries(factors.factor_betas).map(([factor, beta]) => (
                      <div key={factor} className="flex items-center gap-3">
                        <span className="text-xs text-text-secondary w-24 capitalize">{factor.replace("_", " ")}</span>
                        <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden">
                          <div
                            className={`h-full rounded-full ${Number(beta) >= 0 ? "bg-accent" : "bg-signal-red"}`}
                            style={{ width: `${Math.min(Math.abs(Number(beta)) * 50, 100)}%`, marginLeft: Number(beta) < 0 ? "auto" : 0 }}
                          />
                        </div>
                        <span className="text-xs font-mono text-text-primary w-12 text-right">
                          {beta != null ? Number(beta).toFixed(3) : "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {factors.residual_vol != null && (
                <p className="text-xs text-text-quaternary">
                  Residual volatility (idiosyncratic risk): <span className="font-mono text-text-primary">{factors.residual_vol}%</span>
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TradeRow({ trade, onClose }: { trade: Trade; onClose?: (id: string) => void }) {
  const [closing, setClosing] = useState(false);
  const [exitPrice, setExitPrice] = useState("");
  const [showClose, setShowClose] = useState(false);
  const dir = DIRECTION_STYLE[trade.direction as keyof typeof DIRECTION_STYLE] ?? DIRECTION_STYLE.neutral;

  const handleClose = async () => {
    if (!exitPrice) return;
    setClosing(true);
    try {
      await api.closeTrade(trade.id, parseFloat(exitPrice));
      onClose?.(trade.id);
    } catch { /* ignore */ }
    setClosing(false);
  };

  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-[15px] font-mono font-bold text-text-primary">{trade.ticker}</span>
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${dir.color}`}>{trade.action}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            trade.status === "open" ? "bg-signal-green/10 text-signal-green" : "bg-bg-elevated text-text-tertiary"
          }`}>{trade.status}</span>
        </div>
        <span className="text-[11px] text-text-quaternary">
          {trade.opened_at ? new Date(trade.opened_at).toLocaleDateString() : ""}
        </span>
      </div>
      <ConvictionBar value={trade.conviction} size="sm" />
      <p className="text-xs text-text-tertiary mt-2">{trade.thesis}</p>
      <div className="flex items-center gap-4 mt-2 text-[11px]">
        {trade.stop_loss && <span className="text-text-quaternary">Stop: <span className="font-mono text-signal-red">${trade.stop_loss}</span></span>}
        {trade.take_profit && <span className="text-text-quaternary">Target: <span className="font-mono text-signal-green">${trade.take_profit}</span></span>}
        <span className="text-text-quaternary">Size: <span className="font-mono text-text-primary">{trade.position_size_pct}%</span></span>
        {trade.realized_pnl != null && (
          <span className={`font-mono font-medium ${trade.realized_pnl >= 0 ? "text-signal-green" : "text-signal-red"}`}>
            P&L: {trade.realized_pnl > 0 ? "+" : ""}{trade.realized_pnl}%
          </span>
        )}
      </div>

      {/* Close trade */}
      {trade.status === "open" && onClose && (
        <div className="mt-3 pt-3 border-t border-border-primary">
          {showClose ? (
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="0.01"
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
                placeholder="Exit price..."
                className="bg-bg-primary border border-border-primary rounded-lg px-2 py-1 text-xs text-text-primary outline-none w-28"
              />
              <button
                onClick={handleClose}
                disabled={closing || !exitPrice}
                className="px-2 py-1 rounded-lg bg-signal-red/10 text-signal-red text-[11px] font-medium hover:bg-signal-red/20 transition-colors disabled:opacity-40"
              >
                {closing ? "Closing..." : "Confirm Close"}
              </button>
              <button onClick={() => setShowClose(false)} className="text-[11px] text-text-quaternary hover:text-text-tertiary">Cancel</button>
            </div>
          ) : (
            <button
              onClick={() => setShowClose(true)}
              className="text-[11px] text-text-tertiary hover:text-text-secondary transition-colors"
            >
              Close Trade
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-lg font-mono font-medium ${color ?? "text-text-primary"}`}>{value}</p>
    </div>
  );
}
