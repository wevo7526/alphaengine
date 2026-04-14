"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { MacroChart } from "@/components/MacroChart";
import { MemoPanel } from "@/components/MemoPanel";
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

const ALL_INDICATORS: Record<string, string> = {
  fed_funds_rate: "Fed Funds Rate",
  yield_curve_spread: "Yield Curve (10Y-2Y)",
  breakeven_inflation: "Breakeven Inflation",
  credit_spreads: "HY Credit Spreads",
  vix: "VIX",
  unemployment: "Unemployment",
  cpi: "CPI",
  real_gdp: "Real GDP",
  fed_balance_sheet: "Fed Balance Sheet",
  wti_crude: "WTI Crude",
  usd_index: "USD Index",
  m2_money_supply: "M2 Money Supply",
  jobless_claims: "Initial Claims",
};

export default function HomePage() {
  const [macro, setMacro] = useState<MacroDashboard | null>(null);
  const [macroLoading, setMacroLoading] = useState(true);
  const [macroError, setMacroError] = useState<string | null>(null);
  const [morningReport, setMorningReport] = useState<MorningReport | null>(null);
  const [recentMemos, setRecentMemos] = useState<IntelligenceMemo[]>([]);
  const [expandedMemo, setExpandedMemo] = useState<number | null>(null);
  const [regime, setRegime] = useState<Record<string, unknown> | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

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
    }).catch(() => {});

    api.latestMemos(5).then((d: unknown) => {
      if (!cancelled) setRecentMemos((d as { memos: IntelligenceMemo[] }).memos || []);
    }).catch(() => {});

    return () => { cancelled = true; };
  }, []);

  const loadMorningReport = () => {
    setReportLoading(true);
    api.morningReport().then((d: unknown) => {
      setMorningReport(d as MorningReport);
      setReportLoading(false);
    }).catch(() => setReportLoading(false));
  };

  const indicators = macro?.indicators ?? {};
  const series = macro?.series;

  return (
    <div className="p-8 max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
            Dashboard
          </h1>
          <p className="text-sm text-text-tertiary">
            Market overview and intelligence briefing.
          </p>
        </div>
        <Link
          href="/analysis"
          className="px-4 py-2 rounded-xl bg-white text-bg-primary text-[13px] font-medium hover:bg-zinc-200 transition-colors"
        >
          New Analysis
        </Link>
      </div>

      {/* Morning Report */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        {morningReport ? (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-[15px] font-semibold text-text-primary">
                {morningReport.title || "Morning Briefing"}
              </h2>
              <div className="flex items-center gap-3 text-[11px]">
                {morningReport.macro_regime && (
                  <span className="text-text-quaternary">
                    Regime: <span className="text-text-primary font-medium">{morningReport.macro_regime}</span>
                  </span>
                )}
                {morningReport.overall_risk_level && (
                  <span className="text-text-quaternary">
                    Risk: <span className="text-text-primary font-medium">{morningReport.overall_risk_level}</span>
                  </span>
                )}
              </div>
            </div>
            <p className="text-[13px] text-text-secondary leading-relaxed mb-3">
              {morningReport.executive_summary}
            </p>
            {morningReport.key_findings && morningReport.key_findings.length > 0 && (
              <ul className="space-y-1">
                {morningReport.key_findings.slice(0, 4).map((f, i) => (
                  <li key={i} className="text-xs text-text-tertiary flex items-start gap-2">
                    <span className="text-accent mt-0.5 shrink-0">{i + 1}</span>
                    {f}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-[13px] font-medium text-text-primary mb-0.5">Morning Briefing</h2>
              <p className="text-xs text-text-tertiary">Pre-market intelligence with macro regime, risks, and opportunities.</p>
            </div>
            <button
              onClick={loadMorningReport}
              disabled={reportLoading}
              className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-xs font-medium hover:bg-zinc-200 transition-colors disabled:opacity-40"
            >
              {reportLoading ? "Generating..." : "Generate Report"}
            </button>
          </div>
        )}
      </div>

      {/* Regime Detection */}
      {regime && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-4 mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`w-2.5 h-2.5 rounded-full ${
                String(regime.current_regime) === "risk_on" ? "bg-signal-green" :
                String(regime.current_regime) === "risk_off" ? "bg-signal-red" : "bg-signal-yellow"
              }`} />
              <div>
                <p className="text-[11px] text-text-quaternary uppercase tracking-wider">Market Regime</p>
                <p className="text-[15px] font-semibold text-text-primary capitalize">
                  {String(regime.current_regime || "unknown").replace("_", " ")}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-text-quaternary">Confidence:</span>
              <span className="text-sm font-mono text-text-primary">
                {regime.confidence ? `${(Number(regime.confidence) * 100).toFixed(0)}%` : "—"}
              </span>
              <span className="text-[10px] text-text-quaternary ml-2">
                {String(regime.method || "")}
              </span>
            </div>
          </div>
          {regime.probabilities ? (
            <div className="flex gap-2 mt-3">
              {Object.entries(regime.probabilities as Record<string, number>).map(([state, prob]) => (
                <div key={state} className="flex-1 rounded-lg bg-bg-primary px-2 py-1.5 text-center">
                  <p className="text-[9px] text-text-quaternary capitalize">{state.replace("_", " ")}</p>
                  <p className="text-xs font-mono text-text-primary">{(Number(prob) * 100).toFixed(0)}%</p>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}

      {/* Macro Charts */}
      {macroError && (
        <div className="rounded-xl border border-signal-red/20 bg-signal-red/[0.04] p-4 mb-6">
          <p className="text-xs text-signal-red">Macro data error: {macroError}</p>
          <p className="text-[11px] text-text-quaternary mt-1">Make sure the backend is running on the correct port.</p>
        </div>
      )}
      {macroLoading ? (
        <div className="grid grid-cols-2 gap-4 mb-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-xl border border-border-primary bg-bg-surface p-4 h-48 flex items-center justify-center">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
                <span className="text-xs text-text-quaternary">Loading...</span>
              </div>
            </div>
          ))}
        </div>
      ) : series ? (
        <div className="grid grid-cols-2 gap-4 mb-6">
          <MacroChart title="Yield Curve (10Y-2Y)" data={series.yield_curve} color="#3b82f6" unit="%" />
          <MacroChart title="VIX" data={series.vix} color="#ef4444" invertColor />
          <MacroChart title="HY Credit Spreads" data={series.credit_spreads} color="#f59e0b" unit="%" invertColor />
          <MacroChart title="Fed Funds Rate" data={series.fed_funds} color="#8b5cf6" unit="%" />
        </div>
      ) : null}

      {/* All Indicators */}
      {Object.keys(indicators).length > 0 && (
        <div className="rounded-xl border border-border-primary bg-bg-surface overflow-hidden mb-6">
          <div className="px-4 py-3 border-b border-border-primary">
            <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider">
              Economic Indicators
            </h2>
          </div>
          <div className="divide-y divide-border-primary">
            {Object.entries(ALL_INDICATORS).map(([key, label]) => {
              const ind = indicators[key];
              if (!ind) return null;
              return (
                <div key={key} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-[13px] text-text-secondary">{label}</span>
                  <div className="flex items-center gap-3">
                    <span className={`text-[11px] font-mono ${ind.change > 0 ? "text-signal-green" : "text-signal-red"}`}>
                      {ind.change > 0 ? "+" : ""}{ind.change.toFixed(2)}
                    </span>
                    <span className="text-[13px] font-mono font-medium text-text-primary w-20 text-right">
                      {ind.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </span>
                    <span className="text-[10px] text-text-quaternary w-20 text-right">
                      {ind.date}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent Analyses */}
      {recentMemos.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider">
              Recent Analyses
            </h2>
            <Link href="/portfolio" className="text-[11px] text-accent hover:underline">
              View all in Portfolio
            </Link>
          </div>
          <div className="space-y-2">
            {recentMemos.map((memo, i) => (
              <div key={i}>
                <div
                  onClick={() => setExpandedMemo(expandedMemo === i ? null : i)}
                  className="rounded-xl border border-border-primary bg-bg-surface p-4 hover:border-zinc-600 transition-colors cursor-pointer"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[13px] font-medium text-text-primary">
                      {memo.title || memo.query}
                    </span>
                    <div className="flex items-center gap-2">
                      {memo.trade_ideas && memo.trade_ideas.length > 0 && (
                        <div className="flex gap-1">
                          {memo.trade_ideas.slice(0, 4).map((ti, j) => (
                            <span key={j} className="text-[10px] font-mono text-text-quaternary bg-bg-elevated px-1.5 py-0.5 rounded">
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
        </div>
      )}
    </div>
  );
}
