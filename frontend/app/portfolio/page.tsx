"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DIRECTION_STYLE } from "@/lib/types";
import type { IntelligenceMemo } from "@/lib/types";
import { ConvictionBar } from "@/components/ConvictionBar";
import { MemoPanel } from "@/components/MemoPanel";

const API_BASE = (() => {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) return process.env.NEXT_PUBLIC_BACKEND_URL;
  if (typeof window !== "undefined" && window.location.hostname.includes("railway.app"))
    return "https://alpha-backend-production-51df.up.railway.app";
  return "http://localhost:8000";
})();

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
  const [tab, setTab] = useState<"journal" | "analyses" | "backtest" | "factors">("journal");

  useEffect(() => {
    Promise.all([
      api.listTrades("all").then((d: unknown) => {
        setTrades((d as { trades: Trade[] }).trades);
      }).catch(() => {}),
      api.latestMemos(20).then((d: unknown) => {
        setMemos((d as { memos: IntelligenceMemo[] }).memos || []);
      }).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const runBacktest = () => {
    setBacktesting(true);
    fetch(`${API_BASE}/api/portfolio/backtest`)
      .then((r) => r.json())
      .then((d: { trades: BacktestResult[]; summary: BacktestSummary }) => {
        setBacktestResults(d.trades);
        setBacktestSummary(d.summary);
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
        <button
          onClick={runBacktest}
          disabled={backtesting}
          className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-xs font-medium hover:bg-zinc-200 transition-colors disabled:opacity-40"
        >
          {backtesting ? "Running..." : "Run Backtest"}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {[
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
                      <MemoPanel memo={memo} />
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
