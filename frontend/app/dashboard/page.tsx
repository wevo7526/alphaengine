"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useUser } from "@clerk/nextjs";
import { api } from "@/lib/api";
import { MacroChart } from "@/components/MacroChart";
import { MemoPanel } from "@/components/MemoPanel";
import { TerminalHeader } from "@/components/TerminalHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { StatPanel } from "@/components/StatPanel";
import { StatusPill } from "@/components/StatusPill";
import { LedgerRow } from "@/components/LedgerRow";
import type { MacroIndicator, IntelligenceMemo } from "@/lib/types";

interface MacroSeries {
  yield_curve: { date: string; value: number }[];
  vix: { date: string; value: number }[];
  credit_spreads: { date: string; value: number }[];
  fed_funds: { date: string; value: number }[];
}

interface MacroDashboard {
  indicators: Record<string, MacroIndicator>;
  count: number;
  series: MacroSeries;
}

interface PortfolioSummary {
  open_positions: number;
  closed_positions: number;
  total_size_pct: number | null;
  unrealized_pnl_pct: number | null;
  unrealized_pnl_dollars: number | null;
  realized_pnl_pct: number | null;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export default function HomePage() {
  const { user } = useUser();
  const [macro, setMacro] = useState<MacroDashboard | null>(null);
  const [macroLoading, setMacroLoading] = useState(true);
  const [macroError, setMacroError] = useState<string | null>(null);
  const [recentMemos, setRecentMemos] = useState<IntelligenceMemo[]>([]);
  const [memosLoaded, setMemosLoaded] = useState(false);
  const [expandedMemo, setExpandedMemo] = useState<number | null>(null);
  const [regime, setRegime] = useState<Record<string, unknown> | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);

  // A "new" user has finished onboarding but has no memos and no positions
  // yet — show the WelcomeHero instead of the full dashboard frame.
  const isBrandNew =
    memosLoaded &&
    portfolioLoaded &&
    recentMemos.length === 0 &&
    (!portfolio || portfolio.open_positions === 0);

  const recordError = (label: string, e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setApiError(`${label}: ${msg}`);
    if (typeof console !== "undefined") console.error(`[dashboard] ${label}`, e);
  };

  useEffect(() => {
    let cancelled = false;

    api.macroDashboard().then((d: unknown) => {
      if (!cancelled) {
        setMacro(d as MacroDashboard);
        setMacroLoading(false);
      }
    }).catch((e) => {
      if (!cancelled) {
        setMacroError(e instanceof Error ? e.message : "Failed to load macro data");
        setMacroLoading(false);
      }
    });

    api.regime().then((d: unknown) => {
      if (!cancelled) setRegime(d as Record<string, unknown>);
    }).catch((e) => { if (!cancelled) recordError("regime", e); });

    api.latestMemos(5).then((d: unknown) => {
      if (!cancelled) {
        setRecentMemos((d as { memos: IntelligenceMemo[] }).memos || []);
        setMemosLoaded(true);
      }
    }).catch((e) => {
      if (!cancelled) {
        setMemosLoaded(true);
        recordError("recent analyses", e);
      }
    });

    api.positions().then((d: unknown) => {
      if (!cancelled) {
        const data = d as { summary?: PortfolioSummary };
        if (data.summary) setPortfolio(data.summary);
        setPortfolioLoaded(true);
      }
    }).catch(() => {
      if (!cancelled) setPortfolioLoaded(true);
    });

    return () => { cancelled = true; };
  }, []);

  const series = macro?.series;

  // ────────────────────────────────────────────────────────────────────
  // Derived stats for the header strip
  // ────────────────────────────────────────────────────────────────────

  const regimeName = String(regime?.current_regime || "unknown").replace(/_/g, " ");
  const regimeConfidence = regime?.confidence
    ? `${(Number(regime.confidence) * 100).toFixed(0)}%`
    : "—";
  // 4-state HMM taxonomy: risk_on / late_cycle / transition / risk_off.
  // Tone progression: green → yellow → yellow → red. late_cycle reads as
  // yellow because "still ok but cracks showing" deserves the same
  // caution-color as transition; the chart numbers differentiate them.
  const regimeTone: "green" | "red" | "yellow" =
    regime?.current_regime === "risk_on" ? "green" :
    regime?.current_regime === "risk_off" ? "red" :
    "yellow";

  const pnlPct = portfolio?.unrealized_pnl_pct;
  const pnlDisplay = pnlPct != null
    ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`
    : "—";
  const pnlTone: "green" | "red" | "default" =
    pnlPct != null ? (pnlPct >= 0 ? "green" : "red") : "default";

  // US equity market session windows, computed against America/New_York.
  // Minute-precise so PRE-MARKET correctly switches to MARKET OPEN at
  // exactly 9:30, not 9:00 like the old hour-only check.
  //   pre-market : 04:00–09:30
  //   open       : 09:30–16:00
  //   after-hours: 16:00–20:00
  //   closed     : everything else (incl. weekends)
  const nowEst = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const minsEst = nowEst.getHours() * 60 + nowEst.getMinutes();
  const dayEst = nowEst.getDay(); // 0=Sun, 6=Sat
  const isWeekend = dayEst === 0 || dayEst === 6;
  const isPreMarket = !isWeekend && minsEst >= 4 * 60 && minsEst < 9 * 60 + 30;
  const isMarketHours = !isWeekend && minsEst >= 9 * 60 + 30 && minsEst < 16 * 60;
  const isAfterHours = !isWeekend && minsEst >= 16 * 60 && minsEst < 20 * 60;
  const sessionLabel = isPreMarket ? "PRE-MARKET"
    : isMarketHours ? "MARKET OPEN"
    : isAfterHours ? "AFTER HOURS"
    : isWeekend ? "WEEKEND" : "CLOSED";
  const sessionTone: "yellow" | "green" | "neutral" = isPreMarket ? "yellow"
    : isMarketHours ? "green"
    : "neutral";

  const todayLabel = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
  });

  const firstName = user?.firstName || user?.fullName?.split(" ")[0];
  const greeting = firstName ? `Good morning, ${firstName}.` : "Good morning.";

  // Subline summarizing platform state
  const sublineParts: string[] = [];
  if (regime?.current_regime) sublineParts.push(`Regime ${regimeName}`);
  if (portfolio && portfolio.open_positions > 0) {
    sublineParts.push(`${portfolio.open_positions} open position${portfolio.open_positions === 1 ? "" : "s"}`);
    if (pnlPct != null) sublineParts.push(`${pnlDisplay} on the book`);
  } else if (memosLoaded && recentMemos.length > 0) {
    sublineParts.push(`${recentMemos.length} recent ${recentMemos.length === 1 ? "memo" : "memos"}`);
  }
  const subline = sublineParts.length ? sublineParts.join(" · ") + "." : "Live macro feed and pre-market briefing below.";

  return (
    <div className="min-w-0 w-full bg-bg-primary">
      {/* TickerBand was removed from the dashboard — it was the cause of
          15 parallel /api/data/market calls per load and was not vital
          to the platform per user direction. The component still exists
          in /components and can be re-enabled later behind a real-time
          batch quote endpoint. */}

      <div className="p-8 max-w-[1280px] mx-auto min-w-0">
        {apiError && (
          <div className="mb-4 flex items-start justify-between gap-3 rounded-md border border-border-primary bg-bg-surface px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-1.5 h-1.5 rounded-full bg-signal-yellow shrink-0" />
              <p className="text-[11px] font-mono text-text-tertiary truncate">{apiError}</p>
            </div>
            <button
              onClick={() => setApiError(null)}
              className="text-text-quaternary hover:text-text-primary text-xs px-1 shrink-0"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        )}

        {/* Terminal header — timestamped, session-aware. Brand-new users
            also get a small FIRST RUN pill so the page feels welcoming
            without an entire hero card hogging the screen. */}
        <TerminalHeader
          eyebrow={`DASHBOARD · ${todayLabel.toUpperCase()}`}
          title={greeting}
          sub={
            isBrandNew ? (
              <>
                Welcome in. Run your first analysis to start populating these stats.{" "}
                <Link href="/analysis" className="text-accent hover:underline">
                  Start now →
                </Link>
              </>
            ) : (
              subline
            )
          }
          meta={
            <div className="flex items-center gap-2">
              {isBrandNew && <StatusPill label="FIRST RUN" tone="blue" />}
              <StatusPill label={sessionLabel} tone={sessionTone} pulse={isMarketHours} />
            </div>
          }
          className="mb-10"
        />

        {/* Stat strip — 4 panels, gap-px grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden mb-10">
          <StatPanel
            label="REGIME"
            value={<span className="capitalize">{regimeName}</span>}
            unit={regime?.confidence ? regimeConfidence : undefined}
            sub={regime?.method ? `via ${String(regime.method)}` : "—"}
            tone={regimeTone}
          />
          <StatPanel
            label="UNREALIZED P&L"
            value={pnlDisplay}
            sub={
              portfolio?.unrealized_pnl_dollars != null
                ? `$${portfolio.unrealized_pnl_dollars.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                : portfolio ? "No open positions" : "—"
            }
            tone={pnlTone}
          />
          <StatPanel
            label="OPEN POSITIONS"
            value={portfolio?.open_positions ?? "—"}
            sub={
              portfolio && portfolio.total_size_pct != null
                ? `${portfolio.total_size_pct.toFixed(1)}% deployed`
                : "—"
            }
          />
          <StatPanel
            label="RECENT MEMOS"
            value={recentMemos.length}
            sub={
              recentMemos[0]?.created_at
                ? `Latest ${new Date(recentMemos[0].created_at).toLocaleDateString()}`
                : memosLoaded ? "No memos yet" : "—"
            }
          />
        </div>

        {/* Latest Work — full-width, denser, single-column. Replaces the
            old MORNING BRIEFING + LATEST WORK 2-col row. The briefing
            panel was mostly empty + slow to generate; this surfaces what
            actually matters at a glance: decision, conviction, tickers,
            and exec summary on one row per memo. */}
        <div className="mb-10">
          <TerminalPanel
            label="LATEST WORK"
            status={
              <div className="flex items-center gap-3">
                {recentMemos.length > 0 && (
                  <span className="text-text-quaternary">
                    {recentMemos.length} {recentMemos.length === 1 ? "MEMO" : "MEMOS"}
                  </span>
                )}
                <Link
                  href="/analysis"
                  className="text-accent hover:text-text-primary transition-colors"
                >
                  NEW ANALYSIS →
                </Link>
              </div>
            }
            bodyClassName="p-0"
          >
            {recentMemos.length > 0 ? (
              <div className="divide-y divide-border-primary/40">
                {recentMemos.slice(0, 5).map((memo, i) => {
                  const decision = memo.decision || "MEMO";
                  const decisionTone: "green" | "red" | "yellow" | "blue" =
                    decision === "GO" ? "green"
                      : decision === "NO-GO" ? "red"
                      : decision === "WATCH" ? "yellow"
                      : "blue";
                  const tickers = (memo.trade_ideas || []).slice(0, 4);
                  return (
                    <button
                      key={memo.id ?? i}
                      onClick={() => setExpandedMemo(expandedMemo === i ? null : i)}
                      className="w-full text-left grid grid-cols-[auto_1fr_auto_auto] items-center gap-4 px-4 py-3 hover:bg-bg-elevated/40 transition-colors"
                    >
                      <StatusPill label={decision} tone={decisionTone} />
                      <div className="min-w-0">
                        <p className="text-[13px] font-medium text-text-primary truncate">
                          {memo.title || memo.query}
                        </p>
                        <p className="text-[11px] text-text-tertiary line-clamp-1 mt-0.5">
                          {memo.executive_summary}
                        </p>
                      </div>
                      {tickers.length > 0 ? (
                        <div className="hidden md:flex gap-1 shrink-0">
                          {tickers.map((ti, j) => (
                            <span
                              key={j}
                              className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                                ti.direction?.includes("bullish")
                                  ? "text-signal-green bg-signal-green/10"
                                  : ti.direction?.includes("bearish")
                                  ? "text-signal-red bg-signal-red/10"
                                  : "text-text-quaternary bg-bg-elevated"
                              }`}
                            >
                              {ti.ticker}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span />
                      )}
                      <span className="text-[10px] font-mono text-text-quaternary shrink-0 tabular-nums">
                        {memo.created_at
                          ? new Date(memo.created_at).toLocaleDateString()
                          : ""}
                      </span>
                    </button>
                  );
                })}
                <Link
                  href="/memos"
                  className="block px-4 py-2.5 text-[11px] font-mono tracking-wider text-text-quaternary hover:text-text-primary transition-colors text-center border-t border-border-primary/40"
                >
                  VIEW ALL →
                </Link>
              </div>
            ) : (
              <div className="px-5 py-10 text-center">
                <p className="text-[13px] text-text-secondary mb-2">
                  No analyses yet.
                </p>
                <p className="text-[11px] text-text-tertiary mb-5 max-w-sm mx-auto">
                  Ask the desk something. Trade ideas, risk checks, theme research —
                  every memo lands here with sources, levels, and the full thesis.
                </p>
                <Link
                  href="/analysis"
                  className="inline-block px-4 py-2 rounded-md bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 transition-colors"
                >
                  Run an analysis
                </Link>
              </div>
            )}
          </TerminalPanel>
        </div>

        {/* Expanded memo viewer (clicked from Latest Work list) */}
        {expandedMemo != null && (() => {
          const memo = recentMemos[expandedMemo];
          if (!memo) return null;
          return (
            <div className="mb-10">
              <div className="flex items-center justify-between mb-3">
                <p className="text-[11px] font-mono tracking-wider text-text-quaternary">
                  <span className="text-accent">///</span> MEMO PREVIEW
                </p>
                <button
                  onClick={() => setExpandedMemo(null)}
                  className="text-[11px] text-text-quaternary hover:text-text-primary transition-colors"
                >
                  Close ×
                </button>
              </div>
              <MemoPanel
                memo={memo}
                onDelete={(id) => {
                  setRecentMemos((prev) => prev.filter((m) => m.id !== id));
                  setExpandedMemo(null);
                }}
              />
            </div>
          );
        })()}

        {/* Macro panel — errors surface in the panel header instead of a
            screen-wide banner so a FRED stutter doesn't make the whole
            dashboard look broken. */}
        <TerminalPanel
          label="MACRO"
          status={
            <div className="flex items-center gap-3">
              {macroError && <StatusPill label="UNAVAILABLE" tone="red" />}
              <Link
                href="/risk"
                className="text-text-quaternary hover:text-text-secondary transition-colors"
              >
                FULL INDICATORS →
              </Link>
            </div>
          }
          bodyClassName="p-5"
        >
          {macroLoading ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="rounded-md border border-border-primary/60 bg-bg-primary/40 h-32 flex items-center justify-center">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
                    <span className="text-[11px] text-text-quaternary">Loading…</span>
                  </div>
                </div>
              ))}
            </div>
          ) : macroError ? (
            <p className="text-[12px] text-text-tertiary py-4 text-center">
              Macro feed temporarily unavailable. It&apos;ll come back on its own — the dashboard&apos;s
              other panels are unaffected.
            </p>
          ) : series ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <MacroChart title="Yield Curve (10Y-2Y)" data={series.yield_curve} color="#a1a1aa" unit="%" />
              <MacroChart title="VIX" data={series.vix} color="#a1a1aa" invertColor />
              <MacroChart title="HY Credit Spreads" data={series.credit_spreads} color="#a1a1aa" unit="%" invertColor />
              <MacroChart title="Fed Funds Rate" data={series.fed_funds} color="#a1a1aa" unit="%" />
            </div>
          ) : null}
        </TerminalPanel>
      </div>
    </div>
  );
}

// WelcomeHero removed — was hijacking the whole dashboard for new users
// and duplicating content the existing header + stat strip already convey.
// First-run users now get a compact FIRST RUN pill in the header and a
// "Run your first analysis →" link in the sub line. That's enough.
