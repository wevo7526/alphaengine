"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DIRECTION_STYLE } from "@/lib/types";
import { ConvictionBar } from "@/components/ConvictionBar";

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

export default function PortfolioPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);
  const [backtestSummary, setBacktestSummary] = useState<BacktestSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [backtesting, setBacktesting] = useState(false);
  const [tab, setTab] = useState<"positions" | "journal" | "backtest">("positions");
  const [positions, setPositions] = useState<Position[]>([]);
  const [positionsSummary, setPositionsSummary] = useState<PositionsSummary | null>(null);
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const [flushing, setFlushing] = useState(false);

  const recordError = (label: string, e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setApiError(`${label}: ${msg}`);
    if (typeof console !== "undefined") console.error(`[portfolio] ${label}`, e);
  };

  const loadPositions = () => {
    setPositionsLoading(true);
    api
      .positions()
      .then((d: unknown) => {
        const data = d as { positions: Position[]; summary: PositionsSummary };
        setPositions(data.positions || []);
        setPositionsSummary(data.summary || null);
      })
      .catch((e) => recordError("positions", e))
      .finally(() => setPositionsLoading(false));
  };

  const loadTrades = () => {
    setLoading(true);
    api
      .listTrades("all")
      .then((d: unknown) => setTrades((d as { trades: Trade[] }).trades))
      .catch((e) => recordError("trades", e))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadTrades();
    loadPositions();
  }, []);

  const runBacktest = () => {
    setBacktesting(true);
    api
      .evaluateTrades()
      .then((d: unknown) => {
        const data = d as { trades: BacktestResult[]; summary: BacktestSummary };
        setBacktestResults(data.trades);
        setBacktestSummary(data.summary);
        setBacktesting(false);
        setTab("backtest");
      })
      .catch((e) => {
        recordError("backtest", e);
        setBacktesting(false);
      });
  };

  const handleFlush = async () => {
    if (flushing) return;
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        "Delete all OPEN positions for your account? This cannot be undone."
      );
      if (!ok) return;
    }
    setFlushing(true);
    try {
      const res = await api.flushPositions("open");
      loadTrades();
      loadPositions();
      setApiError(
        `Flushed ${res.deleted} open position${res.deleted === 1 ? "" : "s"}`
      );
    } catch (e) {
      recordError("flush positions", e);
    }
    setFlushing(false);
  };

  const openTrades = trades.filter((t) => t.status === "open");

  return (
    <div className="p-8 max-w-4xl">
      {apiError && (
        <div className="mb-4 flex items-start justify-between rounded-xl border border-signal-red/25 bg-signal-red/[0.06] p-3">
          <div>
            <p className="text-xs font-medium text-signal-red">Notice</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{apiError}</p>
          </div>
          <button
            onClick={() => setApiError(null)}
            className="text-text-quaternary hover:text-text-primary text-xs px-2"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
            Portfolio
          </h1>
          <p className="text-sm text-text-tertiary">
            Live positions, trade journal, and paper backtest. Performance
            analytics are on the{" "}
            <a href="/track-record" className="text-accent hover:underline">
              Track Record
            </a>{" "}
            page.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                await api.downloadPdf(
                  api.exportPortfolioUrl(),
                  `alpha-engine-portfolio-${Date.now()}.pdf`
                );
              } catch (e) {
                recordError("export pdf", e);
              }
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
          <button
            onClick={handleFlush}
            disabled={flushing || openTrades.length === 0}
            title="Hard-delete all open positions for your account"
            className="px-3 py-1.5 rounded-lg border border-signal-red/30 bg-signal-red/[0.06] text-signal-red text-xs font-medium hover:bg-signal-red/[0.12] transition-colors disabled:opacity-30"
          >
            {flushing ? "Flushing..." : `Flush Open (${openTrades.length})`}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {[
          { key: "positions" as const, label: "Positions" },
          { key: "journal" as const, label: "Trade Journal" },
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

      {/* Positions Tab */}
      {tab === "positions" && (
        <>
          {positionsLoading ? (
            <p className="text-sm text-text-quaternary">Loading positions...</p>
          ) : !positionsSummary || positions.length === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-[13px] text-text-secondary mb-2">No open positions</p>
              <p className="text-xs text-text-tertiary max-w-sm mx-auto">
                Take a trade from an analysis memo, or import existing trades via the
                Trade Journal tab.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="grid grid-cols-4 gap-3">
                <StatCard
                  label="Total Value"
                  value={`$${positionsSummary.total_market_value.toLocaleString()}`}
                />
                <StatCard
                  label="Unrealized P&L"
                  value={`${positionsSummary.total_unrealized_pnl >= 0 ? "+" : ""}${positionsSummary.total_unrealized_pnl_pct.toFixed(2)}%`}
                  color={
                    positionsSummary.total_unrealized_pnl >= 0
                      ? "text-signal-green"
                      : "text-signal-red"
                  }
                />
                <StatCard
                  label="Realized P&L"
                  value={`${positionsSummary.total_realized_pnl >= 0 ? "+" : ""}$${Math.abs(positionsSummary.total_realized_pnl).toLocaleString()}`}
                  color={
                    positionsSummary.total_realized_pnl >= 0
                      ? "text-signal-green"
                      : "text-signal-red"
                  }
                />
                <StatCard
                  label="Win Rate"
                  value={
                    positionsSummary.win_rate !== null
                      ? `${positionsSummary.win_rate.toFixed(1)}%`
                      : "—"
                  }
                  color={
                    positionsSummary.win_rate !== null && positionsSummary.win_rate >= 50
                      ? "text-signal-green"
                      : positionsSummary.win_rate !== null
                      ? "text-signal-red"
                      : undefined
                  }
                />
              </div>

              <div className="rounded-xl border border-border-primary bg-bg-surface overflow-hidden">
                <div className="px-4 py-3 border-b border-border-primary flex items-center justify-between">
                  <div>
                    <h2 className="text-[13px] font-medium text-text-primary">
                      Open Positions
                    </h2>
                    <p className="text-[10px] text-text-quaternary">
                      {positionsSummary.open_positions} positions · based on $
                      {positionsSummary.portfolio_base.toLocaleString()} portfolio
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
                        const pnlColor =
                          (p.unrealized_pnl_pct ?? 0) >= 0
                            ? "text-signal-green"
                            : "text-signal-red";
                        return (
                          <tr
                            key={`${p.ticker}-${p.direction}-${i}`}
                            className="border-b border-border-primary last:border-b-0 hover:bg-white/[0.02] transition-colors"
                          >
                            <td className="px-4 py-3">
                              <span className="text-[13px] font-mono font-bold text-text-primary">
                                {p.ticker}
                              </span>
                              {p.trade_count > 1 && (
                                <span className="ml-1.5 text-[10px] text-text-quaternary">
                                  ×{p.trade_count}
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <span
                                className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                                  dirLong
                                    ? "bg-signal-green/10 text-signal-green"
                                    : "bg-signal-red/10 text-signal-red"
                                }`}
                              >
                                {dirLong ? "LONG" : "SHORT"}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-secondary">
                              {p.avg_entry_price !== null
                                ? `$${p.avg_entry_price.toFixed(2)}`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-primary">
                              {p.current_price !== null
                                ? `$${p.current_price.toFixed(2)}`
                                : "—"}
                            </td>
                            <td className={`px-4 py-3 text-right font-mono text-[12px] font-medium ${pnlColor}`}>
                              {p.unrealized_pnl_pct !== null
                                ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%`
                                : "—"}
                            </td>
                            <td className={`px-4 py-3 text-right font-mono text-[12px] ${pnlColor}`}>
                              {p.unrealized_pnl_dollars !== null
                                ? `${p.unrealized_pnl_dollars >= 0 ? "+" : ""}$${Math.abs(p.unrealized_pnl_dollars).toFixed(0)}`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-tertiary">
                              {p.weight_pct != null
                                ? `${p.weight_pct.toFixed(1)}%`
                                : p.total_size_pct != null
                                ? `${p.total_size_pct.toFixed(1)}%`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[11px] text-text-quaternary">
                              {p.avg_stop_loss !== null
                                ? `$${p.avg_stop_loss.toFixed(0)}`
                                : "—"}{" "}
                              /{" "}
                              {p.avg_take_profit !== null
                                ? `$${p.avg_take_profit.toFixed(0)}`
                                : "—"}
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

      {/* Trade Journal Tab */}
      {tab === "journal" && (
        <>
          {loading ? (
            <p className="text-sm text-text-quaternary">Loading trades...</p>
          ) : trades.length === 0 ? (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
              <p className="text-[13px] text-text-secondary mb-2">
                No trades in your journal yet
              </p>
              <p className="text-xs text-text-tertiary max-w-sm mx-auto">
                Go to the Analysis page, run a query, and click "Take Trade" on any
                trade idea to start tracking positions and P&L here.
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
                    {openTrades.map((t) => (
                      <TradeRow
                        key={t.id}
                        trade={t}
                        onClose={() => loadTrades()}
                      />
                    ))}
                  </div>
                </div>
              )}
              {trades.filter((t) => t.status !== "open").length > 0 && (
                <div>
                  <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
                    Closed Trades ({trades.filter((t) => t.status !== "open").length})
                  </h2>
                  <div className="space-y-2">
                    {trades
                      .filter((t) => t.status !== "open")
                      .map((t) => (
                        <TradeRow key={t.id} trade={t} />
                      ))}
                  </div>
                </div>
              )}
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
              <StatCard
                label="Wins"
                value={String(backtestSummary.wins)}
                color="text-signal-green"
              />
              <StatCard
                label="Losses"
                value={String(backtestSummary.losses)}
                color="text-signal-red"
              />
              <StatCard
                label="Win Rate"
                value={`${backtestSummary.win_rate}%`}
                color={
                  backtestSummary.win_rate >= 50
                    ? "text-signal-green"
                    : "text-signal-red"
                }
              />
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
                <div
                  key={t.id}
                  className="rounded-xl border border-border-primary bg-bg-surface p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <span className="text-[15px] font-mono font-bold text-text-primary">
                        {t.ticker}
                      </span>
                      <span
                        className={`text-xs ${
                          t.evaluation.status === "target_hit"
                            ? "text-signal-green"
                            : t.evaluation.status === "stopped_out"
                            ? "text-signal-red"
                            : "text-text-tertiary"
                        }`}
                      >
                        {t.evaluation.status === "target_hit"
                          ? "Target Hit"
                          : t.evaluation.status === "stopped_out"
                          ? "Stopped Out"
                          : "Open"}
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
                      <span
                        className={`text-sm font-mono font-medium ${
                          t.evaluation.unrealized_pnl_pct >= 0
                            ? "text-signal-green"
                            : "text-signal-red"
                        }`}
                      >
                        {t.evaluation.unrealized_pnl_pct > 0 ? "+" : ""}
                        {t.evaluation.unrealized_pnl_pct}%
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

function TradeRow({
  trade,
  onClose,
}: {
  trade: Trade;
  onClose?: (id: string) => void;
}) {
  const [closing, setClosing] = useState(false);
  const [exitPrice, setExitPrice] = useState("");
  const [showClose, setShowClose] = useState(false);
  const [marketPrice, setMarketPrice] = useState<number | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const dir =
    DIRECTION_STYLE[trade.direction as keyof typeof DIRECTION_STYLE] ??
    DIRECTION_STYLE.neutral;

  const fetchMarketPrice = async () => {
    setMarketLoading(true);
    try {
      const data = (await api.market(trade.ticker, "1mo")) as {
        fundamentals?: { current_price?: number };
      };
      const price = data.fundamentals?.current_price;
      if (price && price > 0) {
        setMarketPrice(price);
        if (!exitPrice) setExitPrice(price.toFixed(2));
      }
    } catch {
      /* leave blank */
    }
    setMarketLoading(false);
  };

  const openCloseUI = () => {
    setShowClose(true);
    if (!marketPrice) fetchMarketPrice();
  };

  const handleClose = async (priceOverride?: number) => {
    const px = priceOverride ?? parseFloat(exitPrice);
    if (!px || px <= 0) return;
    setClosing(true);
    try {
      await api.closeTrade(trade.id, px);
      onClose?.(trade.id);
    } catch {
      /* ignore */
    }
    setClosing(false);
  };

  const handleCloseAtMarket = async () => {
    if (!marketPrice) {
      await fetchMarketPrice();
      return;
    }
    await handleClose(marketPrice);
  };

  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-[15px] font-mono font-bold text-text-primary">
            {trade.ticker}
          </span>
          <span
            className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${dir.color}`}
          >
            {trade.action}
          </span>
          <span
            className={`text-xs px-2 py-0.5 rounded-full ${
              trade.status === "open"
                ? "bg-signal-green/10 text-signal-green"
                : "bg-bg-elevated text-text-tertiary"
            }`}
          >
            {trade.status}
          </span>
        </div>
        <span className="text-[11px] text-text-quaternary">
          {trade.opened_at ? new Date(trade.opened_at).toLocaleDateString() : ""}
        </span>
      </div>
      <ConvictionBar value={trade.conviction} size="sm" />
      <p className="text-xs text-text-tertiary mt-2">{trade.thesis}</p>
      <div className="flex items-center gap-4 mt-2 text-[11px]">
        {trade.stop_loss && (
          <span className="text-text-quaternary">
            Stop:{" "}
            <span className="font-mono text-signal-red">${trade.stop_loss}</span>
          </span>
        )}
        {trade.take_profit && (
          <span className="text-text-quaternary">
            Target:{" "}
            <span className="font-mono text-signal-green">${trade.take_profit}</span>
          </span>
        )}
        <span className="text-text-quaternary">
          Size:{" "}
          <span className="font-mono text-text-primary">
            {trade.position_size_pct}%
          </span>
        </span>
        {trade.realized_pnl != null && (
          <span
            className={`font-mono font-medium ${
              trade.realized_pnl >= 0 ? "text-signal-green" : "text-signal-red"
            }`}
          >
            P&L: {trade.realized_pnl > 0 ? "+" : ""}
            {trade.realized_pnl}%
          </span>
        )}
      </div>

      {trade.status === "open" && onClose && (
        <div className="mt-3 pt-3 border-t border-border-primary">
          {showClose ? (
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={handleCloseAtMarket}
                disabled={closing || marketLoading}
                className="px-2 py-1 rounded-lg bg-white text-bg-primary text-[11px] font-medium hover:bg-zinc-200 transition-colors disabled:opacity-40"
              >
                {marketLoading
                  ? "Loading market..."
                  : marketPrice
                  ? `Close @ Market $${marketPrice.toFixed(2)}`
                  : "Fetch Market Price"}
              </button>
              <span className="text-[10px] text-text-quaternary">or</span>
              <input
                type="number"
                step="0.01"
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
                placeholder="Custom exit"
                className="bg-bg-primary border border-border-primary rounded-lg px-2 py-1 text-xs text-text-primary outline-none w-24"
              />
              <button
                onClick={() => handleClose()}
                disabled={closing || !exitPrice}
                className="px-2 py-1 rounded-lg bg-signal-red/10 text-signal-red text-[11px] font-medium hover:bg-signal-red/20 transition-colors disabled:opacity-40"
              >
                {closing ? "Closing..." : "Close"}
              </button>
              <button
                onClick={() => setShowClose(false)}
                className="text-[11px] text-text-quaternary hover:text-text-tertiary"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={openCloseUI}
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

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">
        {label}
      </p>
      <p className={`text-lg font-mono font-medium ${color ?? "text-text-primary"}`}>
        {value}
      </p>
    </div>
  );
}
