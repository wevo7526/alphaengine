"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { DIRECTION_STYLE } from "@/lib/types";
import { ConvictionBar } from "@/components/ConvictionBar";
import { TerminalHeader } from "@/components/TerminalHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { StatPanel } from "@/components/StatPanel";
import { StatusPill } from "@/components/StatusPill";

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

type Tab = "positions" | "journal" | "backtest";

export default function PortfolioPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);
  const [backtestSummary, setBacktestSummary] = useState<BacktestSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [backtesting, setBacktesting] = useState(false);
  const [tab, setTab] = useState<Tab>("positions");
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
  const closedTrades = trades.filter((t) => t.status !== "open");

  return (
    <div className="p-8 max-w-[1280px] mx-auto">
      {apiError && (
        <div className="mb-6 flex items-start justify-between rounded-md border border-signal-red/25 bg-signal-red/[0.06] p-3">
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

      <TerminalHeader
        eyebrow="PORTFOLIO"
        title="Live positions and trade journal"
        sub={
          <>
            Performance analytics live on the{" "}
            <Link href="/track-record" className="text-accent hover:underline">
              Track Record
            </Link>{" "}
            page.
          </>
        }
        meta={
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
              className="px-2.5 py-1 rounded-md text-[10px] font-mono tracking-wider text-text-tertiary hover:text-text-primary hover:bg-white/[0.04] transition-colors"
            >
              EXPORT PDF
            </button>
            <button
              onClick={runBacktest}
              disabled={backtesting}
              className="px-2.5 py-1 rounded-md bg-white text-bg-primary text-[10px] font-mono font-semibold tracking-wider hover:bg-zinc-200 transition-colors disabled:opacity-40"
            >
              {backtesting ? "RUNNING…" : "RUN BACKTEST"}
            </button>
            <button
              onClick={handleFlush}
              disabled={flushing || openTrades.length === 0}
              title="Hard-delete all open positions for your account"
              className="px-2.5 py-1 rounded-md border border-signal-red/30 bg-signal-red/[0.06] text-signal-red text-[10px] font-mono tracking-wider hover:bg-signal-red/[0.12] transition-colors disabled:opacity-30"
            >
              {flushing ? "FLUSHING…" : `FLUSH OPEN (${openTrades.length})`}
            </button>
          </div>
        }
        className="mb-8"
      />

      {/* Terminal segment switcher */}
      <div className="inline-flex items-center gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden mb-8 p-px">
        {([
          { key: "positions", label: "POSITIONS", count: positions.length },
          { key: "journal", label: "TRADE JOURNAL", count: trades.length },
          { key: "backtest", label: "BACKTEST", count: backtestResults.length || null },
        ] as { key: Tab; label: string; count: number | null }[]).map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3.5 py-1.5 text-[10px] font-mono tracking-[0.15em] transition-colors ${
                active
                  ? "bg-bg-surface text-text-primary"
                  : "bg-bg-primary text-text-tertiary hover:text-text-secondary"
              }`}
            >
              {t.label}
              {t.count !== null && (
                <span className={`ml-2 ${active ? "text-text-quaternary" : "text-text-quaternary"}`}>
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Positions Tab */}
      {tab === "positions" && (
        <>
          {positionsLoading ? (
            <p className="text-sm text-text-quaternary font-mono">Loading positions…</p>
          ) : !positionsSummary || positions.length === 0 ? (
            <TerminalPanel label="POSITIONS" status="EMPTY">
              <div className="text-center py-6">
                <p className="text-[13px] text-text-secondary mb-2">No open positions.</p>
                <p className="text-[12px] text-text-tertiary max-w-sm mx-auto">
                  Take a trade from an analysis memo, or import existing trades via the
                  Trade Journal tab.
                </p>
              </div>
            </TerminalPanel>
          ) : (
            <div className="space-y-6">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden">
                <StatPanel
                  label="TOTAL VALUE"
                  value={`$${positionsSummary.total_market_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                  sub={`based on $${positionsSummary.portfolio_base.toLocaleString()} portfolio`}
                />
                <StatPanel
                  label="UNREALIZED P&L"
                  value={`${positionsSummary.total_unrealized_pnl >= 0 ? "+" : ""}${positionsSummary.total_unrealized_pnl_pct.toFixed(2)}%`}
                  sub={`${positionsSummary.total_unrealized_pnl >= 0 ? "+" : "-"}$${Math.abs(positionsSummary.total_unrealized_pnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                  tone={positionsSummary.total_unrealized_pnl >= 0 ? "green" : "red"}
                />
                <StatPanel
                  label="REALIZED P&L"
                  value={`${positionsSummary.total_realized_pnl >= 0 ? "+" : "-"}$${Math.abs(positionsSummary.total_realized_pnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                  sub={`${positionsSummary.closed_trades} closed trade${positionsSummary.closed_trades === 1 ? "" : "s"}`}
                  tone={positionsSummary.total_realized_pnl >= 0 ? "green" : "red"}
                />
                <StatPanel
                  label="WIN RATE"
                  value={positionsSummary.win_rate !== null ? `${positionsSummary.win_rate.toFixed(0)}%` : "—"}
                  sub={`${positionsSummary.wins}W / ${positionsSummary.losses}L`}
                  tone={
                    positionsSummary.win_rate !== null && positionsSummary.win_rate >= 50
                      ? "green"
                      : positionsSummary.win_rate !== null
                      ? "red"
                      : "default"
                  }
                />
              </div>

              <TerminalPanel
                label="OPEN POSITIONS"
                status={
                  <button
                    onClick={loadPositions}
                    className="text-text-quaternary hover:text-text-secondary transition-colors"
                  >
                    REFRESH
                  </button>
                }
                bodyClassName="p-0"
              >
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-[10px] text-text-quaternary uppercase tracking-wider border-b border-border-primary/60">
                        <th className="px-4 py-2.5 text-left font-medium">Ticker</th>
                        <th className="px-4 py-2.5 text-left font-medium">Dir</th>
                        <th className="px-4 py-2.5 text-right font-medium">Entry</th>
                        <th className="px-4 py-2.5 text-right font-medium">Current</th>
                        <th className="px-4 py-2.5 text-right font-medium">P&L %</th>
                        <th className="px-4 py-2.5 text-right font-medium">P&L $</th>
                        <th className="px-4 py-2.5 text-right font-medium">Weight</th>
                        <th className="px-4 py-2.5 text-right font-medium">Stop / Target</th>
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
                            className="border-b border-border-primary/40 last:border-b-0 hover:bg-white/[0.02] transition-colors"
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
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-secondary tabular-nums">
                              {p.avg_entry_price !== null
                                ? `$${p.avg_entry_price.toFixed(2)}`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-primary tabular-nums">
                              {p.current_price !== null
                                ? `$${p.current_price.toFixed(2)}`
                                : "—"}
                            </td>
                            <td className={`px-4 py-3 text-right font-mono text-[12px] font-medium tabular-nums ${pnlColor}`}>
                              {p.unrealized_pnl_pct !== null
                                ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%`
                                : "—"}
                            </td>
                            <td className={`px-4 py-3 text-right font-mono text-[12px] tabular-nums ${pnlColor}`}>
                              {p.unrealized_pnl_dollars !== null
                                ? `${p.unrealized_pnl_dollars >= 0 ? "+" : ""}$${Math.abs(p.unrealized_pnl_dollars).toFixed(0)}`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[12px] text-text-tertiary tabular-nums">
                              {p.weight_pct != null
                                ? `${p.weight_pct.toFixed(1)}%`
                                : p.total_size_pct != null
                                ? `${p.total_size_pct.toFixed(1)}%`
                                : "—"}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[11px] text-text-quaternary tabular-nums">
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
              </TerminalPanel>
            </div>
          )}
        </>
      )}

      {/* Trade Journal Tab */}
      {tab === "journal" && (
        <>
          {loading ? (
            <p className="text-sm text-text-quaternary font-mono">Loading trades…</p>
          ) : trades.length === 0 ? (
            <TerminalPanel label="JOURNAL" status="EMPTY">
              <div className="text-center py-6">
                <p className="text-[13px] text-text-secondary mb-2">No trades in your journal yet.</p>
                <p className="text-[12px] text-text-tertiary max-w-sm mx-auto">
                  Go to the Analysis page, run a query, and click &quot;Take Trade&quot; on any
                  trade idea to start tracking positions and P&L here.
                </p>
              </div>
            </TerminalPanel>
          ) : (
            <div className="space-y-6">
              {openTrades.length > 0 && (
                <TerminalPanel
                  label="OPEN POSITIONS"
                  status={`${openTrades.length} OPEN`}
                  bodyClassName="p-0"
                >
                  <div className="divide-y divide-border-primary/40">
                    {openTrades.map((t) => (
                      <TradeRow
                        key={t.id}
                        trade={t}
                        onClose={() => loadTrades()}
                      />
                    ))}
                  </div>
                </TerminalPanel>
              )}
              {closedTrades.length > 0 && (
                <TerminalPanel
                  label="CLOSED TRADES"
                  status={`${closedTrades.length} CLOSED`}
                  bodyClassName="p-0"
                >
                  <div className="divide-y divide-border-primary/40">
                    {closedTrades.map((t) => (
                      <TradeRow key={t.id} trade={t} />
                    ))}
                  </div>
                </TerminalPanel>
              )}
            </div>
          )}
        </>
      )}

      {/* Backtest Tab */}
      {tab === "backtest" && (
        <>
          {backtestSummary && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden mb-6">
              <StatPanel
                label="TOTAL TRADES"
                value={backtestSummary.total}
                sub={`${backtestSummary.open} still open`}
              />
              <StatPanel
                label="WINS"
                value={backtestSummary.wins}
                tone="green"
              />
              <StatPanel
                label="LOSSES"
                value={backtestSummary.losses}
                tone="red"
              />
              <StatPanel
                label="WIN RATE"
                value={`${backtestSummary.win_rate}%`}
                tone={backtestSummary.win_rate >= 50 ? "green" : "red"}
              />
            </div>
          )}

          {backtestResults.length === 0 ? (
            <TerminalPanel label="BACKTEST" status="IDLE">
              <p className="text-[13px] text-text-tertiary text-center py-4">
                Click &quot;RUN BACKTEST&quot; in the header to evaluate open trades against
                current prices.
              </p>
            </TerminalPanel>
          ) : (
            <TerminalPanel
              label="EVALUATION"
              status={`${backtestResults.length} RESULTS`}
              bodyClassName="p-0"
            >
              <div className="divide-y divide-border-primary/40">
                {backtestResults.map((t) => (
                  <div key={t.id} className="px-4 py-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className="text-[15px] font-mono font-bold text-text-primary">
                          {t.ticker}
                        </span>
                        <StatusPill
                          label={
                            t.evaluation.status === "target_hit"
                              ? "TARGET HIT"
                              : t.evaluation.status === "stopped_out"
                              ? "STOPPED OUT"
                              : "OPEN"
                          }
                          tone={
                            t.evaluation.status === "target_hit"
                              ? "green"
                              : t.evaluation.status === "stopped_out"
                              ? "red"
                              : "blue"
                          }
                        />
                      </div>
                      {t.evaluation.current_price && (
                        <span className="text-[13px] font-mono text-text-primary tabular-nums">
                          ${t.evaluation.current_price.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <ConvictionBar value={t.conviction} size="sm" />
                    {t.evaluation.unrealized_pnl_pct != null && (
                      <div className="mt-2 flex items-center gap-2">
                        <span className="text-[10px] font-mono tracking-wider text-text-quaternary">P&L</span>
                        <span
                          className={`text-[13px] font-mono font-medium tabular-nums ${
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
                    <p className="text-[11px] text-text-tertiary mt-2 leading-relaxed">{t.thesis}</p>
                  </div>
                ))}
              </div>
            </TerminalPanel>
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
    <div className="px-4 py-4">
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
          <StatusPill
            label={trade.status}
            tone={trade.status === "open" ? "green" : "neutral"}
          />
        </div>
        <span className="text-[10px] font-mono text-text-quaternary tabular-nums">
          {trade.opened_at ? new Date(trade.opened_at).toLocaleDateString() : ""}
        </span>
      </div>
      <ConvictionBar value={trade.conviction} size="sm" />
      <p className="text-[11px] text-text-tertiary mt-2 leading-relaxed">{trade.thesis}</p>
      <div className="flex items-center gap-4 mt-2 text-[11px] font-mono tabular-nums">
        {trade.stop_loss && (
          <span className="text-text-quaternary">
            STOP <span className="text-signal-red ml-1">${trade.stop_loss}</span>
          </span>
        )}
        {trade.take_profit && (
          <span className="text-text-quaternary">
            TARGET <span className="text-signal-green ml-1">${trade.take_profit}</span>
          </span>
        )}
        <span className="text-text-quaternary">
          SIZE <span className="text-text-primary ml-1">{trade.position_size_pct}%</span>
        </span>
        {trade.realized_pnl != null && (
          <span
            className={`font-medium ${
              trade.realized_pnl >= 0 ? "text-signal-green" : "text-signal-red"
            }`}
          >
            P&L {trade.realized_pnl > 0 ? "+" : ""}
            {trade.realized_pnl}%
          </span>
        )}
      </div>

      {trade.status === "open" && onClose && (
        <div className="mt-3 pt-3 border-t border-border-primary/40">
          {showClose ? (
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={handleCloseAtMarket}
                disabled={closing || marketLoading}
                className="px-2.5 py-1 rounded-md bg-white text-bg-primary text-[11px] font-mono font-semibold hover:bg-zinc-200 transition-colors disabled:opacity-40"
              >
                {marketLoading
                  ? "LOADING…"
                  : marketPrice
                  ? `CLOSE @ MARKET $${marketPrice.toFixed(2)}`
                  : "FETCH MARKET PRICE"}
              </button>
              <span className="text-[10px] font-mono text-text-quaternary">OR</span>
              <input
                type="number"
                step="0.01"
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
                placeholder="Custom exit"
                className="bg-bg-primary border border-border-primary rounded-md px-2 py-1 text-[11px] font-mono text-text-primary outline-none w-24 focus:border-zinc-600"
              />
              <button
                onClick={() => handleClose()}
                disabled={closing || !exitPrice}
                className="px-2.5 py-1 rounded-md bg-signal-red/10 text-signal-red text-[11px] font-mono font-semibold hover:bg-signal-red/20 transition-colors disabled:opacity-40"
              >
                {closing ? "CLOSING…" : "CLOSE"}
              </button>
              <button
                onClick={() => setShowClose(false)}
                className="text-[11px] font-mono text-text-quaternary hover:text-text-tertiary"
              >
                CANCEL
              </button>
            </div>
          ) : (
            <button
              onClick={openCloseUI}
              className="text-[10px] font-mono tracking-wider text-text-tertiary hover:text-text-secondary transition-colors"
            >
              CLOSE TRADE
            </button>
          )}
        </div>
      )}
    </div>
  );
}
