"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CorrelationHeatmap } from "@/components/CorrelationHeatmap";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from "recharts";

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
  error?: string;
}

interface RegimeData {
  current_regime: string;
  probabilities: Record<string, number>;
  confidence: number;
  method: string;
  transition_matrix?: number[][];
}

function Stat({ label, value, color, suffix, help }: { label: string; value: string | null; color?: string; suffix?: string; help?: string }) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1" title={help}>
        {label} {help && <span className="text-text-quaternary cursor-help">ⓘ</span>}
      </p>
      <p className={`text-lg font-mono font-medium ${color ?? "text-text-primary"}`}>
        {value ?? "—"}{suffix}
      </p>
    </div>
  );
}

export default function RiskPage() {
  const [riskData, setRiskData] = useState<RiskData | null>(null);
  const [regime, setRegime] = useState<RegimeData | null>(null);
  const [conditionalReturns, setConditionalReturns] = useState<Record<string, Record<string, number>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasPositions, setHasPositions] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const recordError = (label: string, e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setApiError(`${label}: ${msg}`);
    if (typeof console !== "undefined") console.error(`[risk] ${label}`, e);
  };

  useEffect(() => {
    let cancelled = false;

    // Always load regime — doesn't need positions
    api.regime().then((d: unknown) => {
      if (!cancelled) setRegime(d as RegimeData);
    }).catch((e) => { if (!cancelled) recordError("regime", e); });

    // Load conditional returns
    api.regimeConditionalReturns("SPY").then((d: unknown) => {
      if (!cancelled && d && typeof d === "object" && !("error" in (d as Record<string, unknown>))) {
        setConditionalReturns(d as Record<string, Record<string, number>>);
      }
    }).catch((e) => { if (!cancelled) recordError("regime conditional returns", e); });

    // Try portfolio risk — may fail with no positions
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

    return () => { cancelled = true; };
  }, []);

  return (
    <div className="p-8 max-w-5xl">
      {apiError && (
        <div className="mb-4 flex items-start justify-between rounded-xl border border-signal-red/25 bg-signal-red/[0.06] p-3">
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
      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">Risk Dashboard</h1>
      <p className="text-sm text-text-tertiary mb-8">Market regime, portfolio risk metrics, and circuit breaker status.</p>

      {/* Regime Detection — always visible */}
      {regime && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${
                regime.current_regime === "risk_on" ? "bg-signal-green" :
                regime.current_regime === "risk_off" ? "bg-signal-red" : "bg-signal-yellow"
              }`} />
              <div>
                <p className="text-[11px] text-text-quaternary uppercase tracking-wider">Market Regime</p>
                <p className="text-[17px] font-semibold text-text-primary capitalize">
                  {regime.current_regime.replace("_", " ")}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-sm font-mono text-text-primary">{(regime.confidence * 100).toFixed(0)}%</p>
              <p className="text-[10px] text-text-quaternary">{regime.method}</p>
            </div>
          </div>

          {/* Regime probability bars */}
          <div className="flex gap-2">
            {Object.entries(regime.probabilities || {}).map(([state, prob]) => (
              <div key={state} className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[9px] text-text-quaternary capitalize">{state.replace("_", " ")}</span>
                  <span className="text-[9px] font-mono text-text-tertiary">{(prob * 100).toFixed(0)}%</span>
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
      )}

      {/* Regime Conditional Returns */}
      {conditionalReturns && Object.keys(conditionalReturns).length > 0 && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
            SPY Returns by Regime (Historical)
          </h3>
          <div className="grid grid-cols-3 gap-3">
            {Object.entries(conditionalReturns).map(([regime, stats]) => (
              <div key={regime} className="rounded-lg bg-bg-primary p-3">
                <p className="text-[10px] text-text-quaternary capitalize mb-1">{regime.replace("_", " ")}</p>
                <p className={`text-sm font-mono font-medium ${
                  (stats.annualized_return_pct ?? 0) >= 0 ? "text-signal-green" : "text-signal-red"
                }`}>
                  {stats.annualized_return_pct != null ? `${stats.annualized_return_pct > 0 ? "+" : ""}${stats.annualized_return_pct}%` : "—"} ann.
                </p>
                <p className="text-[10px] text-text-quaternary">
                  Vol: {stats.volatility_pct ?? "—"}% · {stats.observations ?? 0} days · {stats.positive_pct ?? "—"}% up
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Portfolio Risk Metrics — only if positions exist */}
      {loading ? (
        <div className="flex items-center gap-2 p-4">
          <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
          <span className="text-sm text-text-quaternary">Loading portfolio risk...</span>
        </div>
      ) : hasPositions && riskData ? (
        <>
          <div className="grid grid-cols-4 gap-3 mb-6">
            <Stat label="VaR (95%)" value={riskData.var_pct != null ? `${riskData.var_pct}` : null} color="text-signal-red" suffix="%" help="Value at Risk: maximum expected daily loss at 95% confidence" />
            <Stat label="CVaR (95%)" value={riskData.cvar_pct != null ? `${riskData.cvar_pct}` : null} color="text-signal-red" suffix="%" help="Expected Shortfall: average loss in worst 5% of days" />
            <Stat label="Annual Vol" value={riskData.portfolio_vol_annual != null ? `${riskData.portfolio_vol_annual}` : null} suffix="%" help="Annualized portfolio volatility" />
            <Stat label="Positions" value={String(riskData.positions_count)} />
          </div>

          {/* Circuit Breaker */}
          {riskData.circuit_breaker && (
            <div className={`rounded-xl border p-4 mb-6 ${
              riskData.circuit_breaker.color === "green" ? "border-signal-green/20 bg-signal-green/[0.04]" :
              riskData.circuit_breaker.color === "yellow" ? "border-signal-yellow/20 bg-signal-yellow/[0.04]" :
              "border-signal-red/20 bg-signal-red/[0.04]"
            }`}>
              <div className="flex items-center gap-2 mb-1">
                <div className={`w-2 h-2 rounded-full ${
                  riskData.circuit_breaker.color === "green" ? "bg-signal-green" :
                  riskData.circuit_breaker.color === "yellow" ? "bg-signal-yellow" : "bg-signal-red"
                }`} />
                <span className="text-[13px] font-medium text-text-primary capitalize">Circuit Breaker: {riskData.circuit_breaker.status}</span>
              </div>
              <p className="text-xs text-text-tertiary">{riskData.circuit_breaker.action}</p>
            </div>
          )}

          {/* Sector Exposure */}
          {riskData.sector_exposure && Object.keys(riskData.sector_exposure.sector_breakdown || {}).length > 0 && (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider">Sector Exposure</h3>
                <span className={`text-[10px] font-medium ${riskData.sector_exposure.compliant ? "text-signal-green" : "text-signal-red"}`}>
                  {riskData.sector_exposure.compliant ? "Within limits" : "Limit breached"}
                </span>
              </div>
              <div className="space-y-2">
                {Object.entries(riskData.sector_exposure.sector_breakdown).sort((a, b) => b[1] - a[1]).map(([sector, pct]) => (
                  <div key={sector} className="flex items-center gap-3">
                    <span className="text-xs text-text-secondary w-32 truncate">{sector}</span>
                    <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden relative">
                      <div className={`h-full rounded-full ${pct > 30 ? "bg-signal-red" : "bg-accent"}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                      <div className="absolute top-0 left-[30%] w-px h-full bg-text-quaternary/30" title="30% limit" />
                    </div>
                    <span className="text-xs font-mono text-text-primary w-10 text-right">{pct}%</span>
                  </div>
                ))}
              </div>
              {riskData.sector_exposure.violations?.length > 0 && (
                <div className="mt-3 pt-3 border-t border-border-primary">
                  {riskData.sector_exposure.violations.map((v, i) => (
                    <p key={i} className="text-xs text-signal-red">
                      {v.sector}: {v.current_pct}% exceeds {v.limit_pct}% limit
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Correlation Matrix */}
          {riskData.correlation_matrix && riskData.correlation_matrix.matrix?.length > 1 && (
            <div className="mb-6">
              <CorrelationHeatmap tickers={riskData.correlation_matrix.tickers} matrix={riskData.correlation_matrix.matrix} />
            </div>
          )}
        </>
      ) : (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-6 text-center">
          <p className="text-[13px] text-text-secondary mb-1">No open positions</p>
          <p className="text-xs text-text-tertiary">
            Portfolio risk metrics (VaR, CVaR, sector exposure, correlation) require open trades.
            Run an analysis and take some trades to see your portfolio risk profile here.
          </p>
        </div>
      )}
    </div>
  );
}
