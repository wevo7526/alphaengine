"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { CorrelationHeatmap } from "@/components/CorrelationHeatmap";
import { TerminalHeader } from "@/components/TerminalHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { StatPanel } from "@/components/StatPanel";
import { StatusPill } from "@/components/StatusPill";
import type { MacroIndicator } from "@/lib/types";

interface RiskData {
  var_pct: number | null;
  var_dollars: number | null;
  cvar_pct: number | null;
  portfolio_vol_annual: number | null;
  sector_exposure: {
    sector_breakdown: Record<string, number>;
    violations: { sector: string; current_pct: number; limit_pct: number }[];
    compliant: boolean;
  };
  circuit_breaker: { status: string; action: string; color: string };
  correlation_matrix: { tickers: string[]; matrix: number[][] };
  positions_count: number;
  portfolio_drawdown_pct?: number;
  cornish_fisher?: {
    var_pct: number | null;
    skewness: number | null;
    excess_kurtosis: number | null;
    z_adjusted: number | null;
  };
  historical?: {
    var_pct: number | null;
    ci_95_low_pct: number | null;
    ci_95_high_pct: number | null;
    bootstrap_samples: number;
  };
  sample_size?: number;
  low_sample?: boolean;
  error?: string;
}

interface StressData {
  portfolio_base: number;
  position_count: number;
  historical: Record<string, {
    label: string;
    window: string;
    spy_return_pct: number;
    portfolio_pnl_pct: number;
    portfolio_pnl_dollars: number;
    vix_peak: number;
  }>;
  hypothetical: Array<{
    shock: { type?: string; size?: number; unit?: string } | Record<string, unknown>;
    portfolio_pnl_pct: number;
    portfolio_pnl_dollars: number;
    components?: Array<{
      shock: { type?: string; size?: number; unit?: string };
      portfolio_pnl_pct: number;
    }>;
  }>;
  error?: string;
}

interface RegimeData {
  current_regime: string;
  probabilities: Record<string, number>;
  confidence: number;
  method: string;
  transition_matrix?: number[][];
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

export default function RiskPage() {
  const [riskData, setRiskData] = useState<RiskData | null>(null);
  const [regime, setRegime] = useState<RegimeData | null>(null);
  const [conditionalReturns, setConditionalReturns] = useState<Record<string, Record<string, number>> | null>(null);
  const [stress, setStress] = useState<StressData | null>(null);
  const [macroIndicators, setMacroIndicators] = useState<Record<string, MacroIndicator> | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasPositions, setHasPositions] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [showAllIndicators, setShowAllIndicators] = useState(false);

  const recordError = (label: string, e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setApiError(`${label}: ${msg}`);
    if (typeof console !== "undefined") console.error(`[risk] ${label}`, e);
  };

  useEffect(() => {
    let cancelled = false;

    api.regime().then((d: unknown) => {
      if (!cancelled) setRegime(d as RegimeData);
    }).catch((e) => { if (!cancelled) recordError("regime", e); });

    api.regimeConditionalReturns("SPY").then((d: unknown) => {
      if (!cancelled && d && typeof d === "object" && !("error" in (d as Record<string, unknown>))) {
        setConditionalReturns(d as Record<string, Record<string, number>>);
      }
    }).catch((e) => { if (!cancelled) recordError("regime conditional returns", e); });

    api.portfolioRisk().then((d: unknown) => {
      if (!cancelled) {
        const data = d as RiskData;
        setRiskData(data);
        setHasPositions(!data.error);
      }
      setLoading(false);
    }).catch((e) => {
      if (!cancelled) {
        recordError("portfolio risk", e);
        setLoading(false);
      }
    });

    api.stress().then((d: unknown) => {
      if (!cancelled) {
        const data = d as StressData;
        if (!data.error) setStress(data);
      }
    }).catch(() => { /* no positions / unavailable */ });

    // Load full macro indicators table — moved here from /dashboard.
    api.macroDashboard().then((d: unknown) => {
      if (!cancelled) {
        const data = d as { indicators: Record<string, MacroIndicator> };
        setMacroIndicators(data.indicators || null);
      }
    }).catch(() => { /* macro errors surfaced elsewhere */ });

    return () => { cancelled = true; };
  }, []);

  const regimeTone: "green" | "red" | "yellow" =
    regime?.current_regime === "risk_on" ? "green" :
    regime?.current_regime === "risk_off" ? "red" : "yellow";

  return (
    <div className="p-8 max-w-[1280px] mx-auto">
      {apiError && (
        <div className="mb-6 flex items-start justify-between rounded-md border border-signal-red/25 bg-signal-red/[0.06] p-3">
          <div>
            <p className="text-xs font-medium text-signal-red">Data load issue</p>
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
        eyebrow="RISK"
        title="Risk dashboard"
        sub="Market regime, portfolio risk metrics, and circuit breaker status."
        meta={
          <Link
            href="/risk-config"
            className="px-2.5 py-1 rounded-md border border-border-primary text-text-tertiary hover:text-text-primary hover:border-zinc-600 transition-colors"
          >
            GATE CONFIG →
          </Link>
        }
        className="mb-8"
      />

      {/* MACRO REGIME — current regime + conditional returns collapsed into one panel */}
      {regime && (
        <TerminalPanel
          label="MACRO REGIME"
          status={
            <span className="text-text-quaternary">
              {regime.method?.toUpperCase()}
            </span>
          }
          className="mb-6"
        >
          <div className="grid lg:grid-cols-[1fr_2fr] gap-6 items-start">
            {/* Left: current regime + confidence */}
            <div>
              <StatusPill
                label={regime.current_regime.replace(/_/g, " ")}
                tone={regimeTone}
                pulse
              />
              <div className="mt-4">
                <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
                  CONFIDENCE
                </p>
                <p className="text-[36px] font-semibold tracking-tight text-text-primary tabular-nums leading-none counter-tick">
                  {(regime.confidence * 100).toFixed(0)}<span className="text-[16px] font-mono text-text-tertiary ml-1">%</span>
                </p>
              </div>
              {/* Probability bars */}
              <div className="mt-5 space-y-2">
                {Object.entries(regime.probabilities || {}).map(([state, prob]) => (
                  <div key={state}>
                    <div className="flex items-center justify-between mb-1 text-[10px] font-mono">
                      <span className="text-text-quaternary uppercase tracking-wider">{state.replace(/_/g, " ")}</span>
                      <span className="text-text-tertiary tabular-nums">{(prob * 100).toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-bg-elevated overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          state === "risk_on" ? "bg-signal-green" :
                          state === "risk_off" ? "bg-signal-red" : "bg-signal-yellow"
                        }`}
                        style={{ width: `${prob * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            {/* Right: SPY conditional returns */}
            <div>
              <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-3">
                SPY HISTORICAL RETURNS BY REGIME
              </p>
              {conditionalReturns && Object.keys(conditionalReturns).length > 0 ? (
                <div className="grid grid-cols-3 gap-2">
                  {Object.entries(conditionalReturns).map(([key, stats]) => (
                    <div key={key} className="rounded-md border border-border-primary/60 bg-bg-primary/40 px-3 py-3">
                      <p className="text-[10px] font-mono text-text-quaternary uppercase tracking-wider mb-1.5 truncate">
                        {key.replace(/_/g, " ")}
                      </p>
                      <p className={`text-[18px] font-semibold tabular-nums font-mono ${
                        (stats.annualized_return_pct ?? 0) >= 0 ? "text-signal-green" : "text-signal-red"
                      }`}>
                        {stats.annualized_return_pct != null
                          ? `${stats.annualized_return_pct > 0 ? "+" : ""}${stats.annualized_return_pct}%`
                          : "—"}
                      </p>
                      <p className="text-[10px] text-text-quaternary mt-1 font-mono">
                        VOL {stats.volatility_pct ?? "—"}% · {stats.observations ?? 0}D · {stats.positive_pct ?? "—"}% UP
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[12px] text-text-quaternary">No conditional return data available.</p>
              )}
            </div>
          </div>
        </TerminalPanel>
      )}

      {/* Portfolio Risk Metrics */}
      {loading ? (
        <div className="flex items-center gap-2 p-4">
          <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
          <span className="text-sm text-text-quaternary">Loading portfolio risk…</span>
        </div>
      ) : hasPositions && riskData ? (
        <>
          {/* 4-stat strip */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden mb-6">
            <StatPanel
              label="VAR (95%)"
              value={riskData.var_pct != null ? `${riskData.var_pct}%` : "—"}
              tone="red"
              sub="Parametric Gaussian"
            />
            <StatPanel
              label="CVAR (95%)"
              value={riskData.cvar_pct != null ? `${riskData.cvar_pct}%` : "—"}
              tone="red"
              sub="Expected shortfall"
            />
            <StatPanel
              label="ANNUAL VOL"
              value={riskData.portfolio_vol_annual != null ? `${riskData.portfolio_vol_annual}%` : "—"}
              sub="Annualized portfolio vol"
            />
            <StatPanel
              label="POSITIONS"
              value={riskData.positions_count}
              sub="Open across book"
            />
          </div>

          {/* VaR rigor: Cornish-Fisher + bootstrap CI */}
          {(riskData.cornish_fisher || riskData.historical) && (
            <TerminalPanel
              label="VAR DETAIL"
              status={
                riskData.low_sample ? (
                  <span className="text-signal-yellow">LOW SAMPLE (n={riskData.sample_size})</span>
                ) : undefined
              }
              className="mb-6"
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {riskData.cornish_fisher && riskData.cornish_fisher.var_pct != null && (
                  <div className="rounded-md border border-border-primary/60 bg-bg-primary/40 p-3">
                    <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-1.5">
                      CORNISH-FISHER (TAIL-ADJUSTED)
                    </p>
                    <p className="text-[20px] font-mono font-semibold text-signal-red tabular-nums">
                      {riskData.cornish_fisher.var_pct}%
                    </p>
                    <p className="text-[10px] font-mono text-text-quaternary mt-1.5">
                      skew {riskData.cornish_fisher.skewness} · excess kurtosis {riskData.cornish_fisher.excess_kurtosis} · z* {riskData.cornish_fisher.z_adjusted}
                    </p>
                  </div>
                )}
                {riskData.historical && riskData.historical.var_pct != null && (
                  <div className="rounded-md border border-border-primary/60 bg-bg-primary/40 p-3">
                    <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-1.5">
                      HISTORICAL (BOOTSTRAP)
                    </p>
                    <p className="text-[20px] font-mono font-semibold text-signal-red tabular-nums">
                      {riskData.historical.var_pct}%
                      <span className="text-[11px] text-text-quaternary ml-2 font-normal">
                        [{riskData.historical.ci_95_low_pct}, {riskData.historical.ci_95_high_pct}]
                      </span>
                    </p>
                    <p className="text-[10px] font-mono text-text-quaternary mt-1.5">
                      95% CI · {riskData.historical.bootstrap_samples} resamples
                    </p>
                  </div>
                )}
              </div>
            </TerminalPanel>
          )}

          {/* Circuit Breaker */}
          {riskData.circuit_breaker && (
            <div className={`rounded-md border p-4 mb-6 ${
              riskData.circuit_breaker.color === "green" ? "border-signal-green/30 bg-signal-green/[0.04]" :
              riskData.circuit_breaker.color === "yellow" ? "border-signal-yellow/30 bg-signal-yellow/[0.04]" :
              "border-signal-red/30 bg-signal-red/[0.04]"
            }`}>
              <div className="flex items-center gap-3 mb-1">
                <StatusPill
                  label={`CIRCUIT BREAKER · ${riskData.circuit_breaker.status.toUpperCase()}`}
                  tone={
                    riskData.circuit_breaker.color === "green" ? "green" :
                    riskData.circuit_breaker.color === "yellow" ? "yellow" : "red"
                  }
                  pulse={riskData.circuit_breaker.color !== "green"}
                />
              </div>
              <p className="text-[12px] text-text-secondary mt-2 leading-relaxed">{riskData.circuit_breaker.action}</p>
            </div>
          )}

          {/* Sector Exposure */}
          {riskData.sector_exposure && Object.keys(riskData.sector_exposure.sector_breakdown || {}).length > 0 && (
            <TerminalPanel
              label="SECTOR EXPOSURE"
              status={
                <StatusPill
                  label={riskData.sector_exposure.compliant ? "WITHIN LIMITS" : "LIMIT BREACHED"}
                  tone={riskData.sector_exposure.compliant ? "green" : "red"}
                />
              }
              className="mb-6"
            >
              <div className="space-y-2">
                {Object.entries(riskData.sector_exposure.sector_breakdown).sort((a, b) => b[1] - a[1]).map(([sector, pct]) => (
                  <div key={sector} className="flex items-center gap-3">
                    <span className="text-[12px] text-text-secondary w-32 truncate">{sector}</span>
                    <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden relative">
                      <div className={`h-full rounded-full ${pct > 30 ? "bg-signal-red" : "bg-accent"}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                      <div className="absolute top-0 left-[30%] w-px h-full bg-text-quaternary/40" title="30% limit" />
                    </div>
                    <span className="text-[12px] font-mono text-text-primary w-12 text-right tabular-nums">{pct}%</span>
                  </div>
                ))}
              </div>
              {riskData.sector_exposure.violations?.length > 0 && (
                <div className="mt-4 pt-3 border-t border-border-primary/40">
                  {riskData.sector_exposure.violations.map((v, i) => (
                    <p key={i} className="text-[12px] font-mono text-signal-red">
                      {v.sector}: {v.current_pct}% exceeds {v.limit_pct}% limit
                    </p>
                  ))}
                </div>
              )}
            </TerminalPanel>
          )}

          {/* Correlation Matrix */}
          {riskData.correlation_matrix && riskData.correlation_matrix.matrix?.length > 1 && (
            <TerminalPanel
              label="CORRELATION"
              status={`${riskData.correlation_matrix.tickers.length}×${riskData.correlation_matrix.tickers.length}`}
              className="mb-6"
            >
              <CorrelationHeatmap tickers={riskData.correlation_matrix.tickers} matrix={riskData.correlation_matrix.matrix} />
            </TerminalPanel>
          )}

          {/* Stress Test */}
          {stress && (Object.keys(stress.historical || {}).length > 0 || (stress.hypothetical?.length ?? 0) > 0) && (
            <TerminalPanel
              label="STRESS TEST"
              status={`${stress.position_count} POS · $${(stress.portfolio_base / 1000).toFixed(0)}K BASE`}
              className="mb-6"
            >
              {Object.keys(stress.historical || {}).length > 0 && (
                <div className="space-y-1.5 mb-4">
                  {Object.entries(stress.historical).map(([key, sc]) => {
                    const pnl = sc.portfolio_pnl_pct;
                    const color = pnl >= 0 ? "text-signal-green" : pnl <= -10 ? "text-signal-red" : "text-signal-yellow";
                    return (
                      <div key={key} className="flex items-center justify-between text-[12px] py-1.5 border-b border-border-primary/40 last:border-b-0">
                        <div className="flex-1 min-w-0">
                          <span className="text-text-secondary">{sc.label}</span>
                          <span className="text-[10px] font-mono text-text-quaternary ml-2">
                            SPY {sc.spy_return_pct >= 0 ? "+" : ""}{sc.spy_return_pct}% · VIX peak {sc.vix_peak}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <span className={`font-mono tabular-nums ${color}`}>
                            {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
                          </span>
                          <span className="text-[10px] font-mono text-text-quaternary w-16 text-right tabular-nums">
                            {pnl >= 0 ? "+" : "−"}${Math.abs(sc.portfolio_pnl_dollars).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {stress.hypothetical && stress.hypothetical.length > 0 && (
                <div>
                  <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2.5">HYPOTHETICAL SHOCKS</p>
                  <div className="flex flex-wrap gap-1.5">
                    {stress.hypothetical.map((h, i) => {
                      const shock = h.shock as { type?: string; size?: number; unit?: string; label?: string };
                      const label = shock.label
                        ? shock.label
                        : shock.type === "vix_spike" ? `VIX +${shock.size}`
                        : shock.type === "credit_widen" ? `Credit +${shock.size}bp`
                        : shock.type === "oil_shock" ? `Oil ${(shock.size ?? 0) >= 0 ? "+" : ""}${shock.size}%`
                        : shock.type ?? "shock";
                      const pnl = h.portfolio_pnl_pct;
                      const color = pnl >= 0
                        ? "border-signal-green/30 bg-signal-green/[0.06] text-signal-green"
                        : pnl <= -5
                        ? "border-signal-red/30 bg-signal-red/[0.06] text-signal-red"
                        : "border-signal-yellow/30 bg-signal-yellow/[0.06] text-signal-yellow";
                      return (
                        <div key={i} className={`rounded-md border px-2.5 py-1 text-[11px] font-mono tabular-nums ${color}`}>
                          {label}: {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </TerminalPanel>
          )}
        </>
      ) : (
        <TerminalPanel label="PORTFOLIO RISK" status="NO POSITIONS" className="mb-6">
          <div className="text-center py-4">
            <p className="text-[13px] text-text-secondary mb-1">No open positions.</p>
            <p className="text-[12px] text-text-tertiary max-w-md mx-auto">
              Portfolio risk metrics (VaR, CVaR, sector exposure, correlation) require open trades.
              Run an analysis and take some trades to see your portfolio risk profile here.
            </p>
          </div>
        </TerminalPanel>
      )}

      {/* ALL INDICATORS — collapsible, moved from /dashboard */}
      {macroIndicators && Object.keys(macroIndicators).length > 0 && (
        <TerminalPanel
          label="ALL MACRO INDICATORS"
          status={
            <button
              onClick={() => setShowAllIndicators((v) => !v)}
              className="text-text-tertiary hover:text-text-secondary transition-colors"
            >
              {showAllIndicators ? "HIDE −" : "SHOW +"}
            </button>
          }
          bodyClassName={showAllIndicators ? "p-0" : "p-0"}
          className="mb-6"
        >
          {showAllIndicators ? (
            <div className="divide-y divide-border-primary/40">
              {Object.entries(ALL_INDICATORS).map(([key, label]) => {
                const ind = macroIndicators[key];
                if (!ind) return null;
                return (
                  <div key={key} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-[13px] text-text-secondary">{label}</span>
                    <div className="flex items-center gap-3">
                      <span className={`text-[11px] font-mono tabular-nums ${ind.change > 0 ? "text-signal-green" : "text-signal-red"}`}>
                        {ind.change > 0 ? "+" : ""}{ind.change.toFixed(2)}
                      </span>
                      <span className="text-[13px] font-mono font-medium text-text-primary w-20 text-right tabular-nums">
                        {ind.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </span>
                      <span className="text-[10px] font-mono text-text-quaternary w-20 text-right">
                        {ind.date}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="px-4 py-3 text-[12px] text-text-tertiary">
              {Object.keys(macroIndicators).length} indicators tracked. Click SHOW to view.
            </div>
          )}
        </TerminalPanel>
      )}
    </div>
  );
}
