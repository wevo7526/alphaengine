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

interface MorningReport {
  title?: string;
  executive_summary?: string;
  key_findings?: string[];
  macro_regime?: string;
  overall_risk_level?: string;
  trade_ideas?: { ticker: string; direction: string; conviction: number; thesis: string }[];
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
  const [morningReport, setMorningReport] = useState<MorningReport | null>(null);
  const [recentMemos, setRecentMemos] = useState<IntelligenceMemo[]>([]);
  const [memosLoaded, setMemosLoaded] = useState(false);
  const [expandedMemo, setExpandedMemo] = useState<number | null>(null);
  const [regime, setRegime] = useState<Record<string, unknown> | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
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

    // Auto-load morning report only between 4:00-8:30 AM EST
    const now = new Date();
    const estHour = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" })).getHours();
    const estMin = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" })).getMinutes();
    const isPreMarket = estHour >= 4 && (estHour < 8 || (estHour === 8 && estMin <= 30));

    if (isPreMarket) {
      setReportLoading(true);
      api.morningReport().then((d: unknown) => {
        if (!cancelled) {
          setMorningReport(d as MorningReport);
          setReportLoading(false);
        }
      }).catch(() => { if (!cancelled) setReportLoading(false); });
    }

    return () => { cancelled = true; };
  }, []);

  const loadMorningReport = () => {
    setReportLoading(true);
    api.morningReport().then((d: unknown) => {
      setMorningReport(d as MorningReport);
      setReportLoading(false);
    }).catch((e) => {
      recordError("morning report", e);
      setReportLoading(false);
    });
  };

  const series = macro?.series;

  // ────────────────────────────────────────────────────────────────────
  // Derived stats for the header strip
  // ────────────────────────────────────────────────────────────────────

  const regimeName = String(regime?.current_regime || "unknown").replace(/_/g, " ");
  const regimeConfidence = regime?.confidence
    ? `${(Number(regime.confidence) * 100).toFixed(0)}%`
    : "—";
  const regimeTone: "green" | "red" | "yellow" =
    regime?.current_regime === "risk_on" ? "green" :
    regime?.current_regime === "risk_off" ? "red" : "yellow";

  const pnlPct = portfolio?.unrealized_pnl_pct;
  const pnlDisplay = pnlPct != null
    ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`
    : "—";
  const pnlTone: "green" | "red" | "default" =
    pnlPct != null ? (pnlPct >= 0 ? "green" : "red") : "default";

  // Pre-market window for the header status pill
  const nowEst = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const estHour = nowEst.getHours();
  const isPreMarket = estHour >= 4 && estHour < 9;
  const isMarketHours = (estHour >= 9 && estHour < 16);
  const sessionLabel = isPreMarket ? "PRE-MARKET" : isMarketHours ? "MARKET OPEN" : "AFTER HOURS";
  const sessionTone: "yellow" | "green" | "neutral" = isPreMarket ? "yellow" : isMarketHours ? "green" : "neutral";

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

        {/* Asymmetric content row — same shape for new and returning users.
            Empty states inside each panel are intentionally light; the
            FIRST RUN pill in the header carries the "you're new" message. */}
        <div className="grid lg:grid-cols-12 gap-6 mb-10">
            {/* Morning Briefing — col-span-7 */}
            <div className="lg:col-span-7">
              <TerminalPanel
                label="MORNING BRIEFING"
                status={
                  morningReport
                    ? <StatusPill label="LATEST" tone="green" />
                    : reportLoading
                      ? "Generating…"
                      : "Idle"
                }
              >
                {morningReport ? (
                  <div>
                    <div className="flex items-center gap-3 text-[11px] mb-4">
                      {morningReport.macro_regime && (
                        <span className="text-text-quaternary">
                          REGIME <span className="text-text-primary font-mono ml-1.5">{morningReport.macro_regime}</span>
                        </span>
                      )}
                      {morningReport.overall_risk_level && (
                        <span className="text-text-quaternary">
                          RISK <span className="text-text-primary font-mono ml-1.5">{morningReport.overall_risk_level}</span>
                        </span>
                      )}
                    </div>
                    <p className="text-[13px] text-text-secondary leading-relaxed mb-4">
                      {morningReport.executive_summary}
                    </p>
                    {morningReport.key_findings && morningReport.key_findings.length > 0 && (
                      <ul className="space-y-1.5">
                        {morningReport.key_findings.slice(0, 4).map((f, i) => (
                          <li key={i} className="text-[12px] text-text-tertiary flex items-start gap-2.5">
                            <span className="text-accent mt-0.5 shrink-0 font-mono text-[10px]">{String(i + 1).padStart(2, "0")}</span>
                            {f}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ) : reportLoading ? (
                  <div className="flex items-center gap-3 py-4">
                    <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
                    <p className="text-[12px] text-text-tertiary">Generating pre-market intelligence…</p>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-4 py-1">
                    <p className="text-[12px] text-text-tertiary">
                      Generate a pre-market briefing covering macro regime, risk posture, and
                      the trade ideas worth looking at today.
                    </p>
                    <button
                      onClick={loadMorningReport}
                      className="shrink-0 px-3 py-1.5 rounded-md bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 transition-colors"
                    >
                      Generate
                    </button>
                  </div>
                )}
              </TerminalPanel>
            </div>

            {/* What's new since yesterday — col-span-5 */}
            <div className="lg:col-span-5">
              <TerminalPanel
                label="LATEST WORK"
                status={recentMemos.length > 0 ? `${recentMemos.length} MEMOS` : "EMPTY"}
                bodyClassName="p-0"
              >
                {recentMemos.length > 0 ? (
                  <div className="divide-y divide-border-primary/40">
                    {recentMemos.slice(0, 4).map((memo, i) => (
                      <button
                        key={memo.id ?? i}
                        onClick={() => setExpandedMemo(expandedMemo === i ? null : i)}
                        className="w-full text-left px-4 py-3 hover:bg-bg-elevated/40 transition-colors"
                      >
                        <div className="flex items-center justify-between gap-3 mb-1">
                          <span className="text-[12px] font-medium text-text-primary truncate">
                            {memo.title || memo.query}
                          </span>
                          <span className="text-[10px] font-mono text-text-quaternary shrink-0">
                            {memo.created_at ? new Date(memo.created_at).toLocaleDateString() : ""}
                          </span>
                        </div>
                        <p className="text-[11px] text-text-tertiary line-clamp-1">
                          {memo.executive_summary}
                        </p>
                      </button>
                    ))}
                    <Link
                      href="/memos"
                      className="block px-4 py-2.5 text-[11px] font-mono tracking-wider text-text-quaternary hover:text-text-secondary transition-colors text-center border-t border-border-primary/40"
                    >
                      VIEW ALL →
                    </Link>
                  </div>
                ) : (
                  <div className="px-5 py-6 text-center">
                    <p className="text-[12px] text-text-tertiary mb-3">No memos yet.</p>
                    <Link
                      href="/analysis"
                      className="inline-block px-3 py-1.5 rounded-md bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 transition-colors"
                    >
                      Run an analysis
                    </Link>
                  </div>
                )}
              </TerminalPanel>
            </div>
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
              <MacroChart title="Yield Curve (10Y-2Y)" data={series.yield_curve} color="#3b82f6" unit="%" />
              <MacroChart title="VIX" data={series.vix} color="#ef4444" invertColor />
              <MacroChart title="HY Credit Spreads" data={series.credit_spreads} color="#f59e0b" unit="%" invertColor />
              <MacroChart title="Fed Funds Rate" data={series.fed_funds} color="#8b5cf6" unit="%" />
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
