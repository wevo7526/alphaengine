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
  const [tab, setTab] = useState<"journal" | "analyses" | "backtest">("journal");

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
              <p className="text-sm text-text-tertiary">
                No trades yet. Run an analysis and click "Take Trade" on a trade idea.
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
                    {openTrades.map((t) => <TradeRow key={t.id} trade={t} />)}
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
    </div>
  );
}

function TradeRow({ trade }: { trade: Trade }) {
  const dir = DIRECTION_STYLE[trade.direction as keyof typeof DIRECTION_STYLE] ?? DIRECTION_STYLE.neutral;
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
      </div>
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
