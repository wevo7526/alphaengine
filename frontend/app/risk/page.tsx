"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CorrelationHeatmap } from "@/components/CorrelationHeatmap";

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

function StatCard({ label, value, color, suffix }: { label: string; value: string | null; color?: string; suffix?: string }) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
      <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-lg font-mono font-medium ${color ?? "text-text-primary"}`}>
        {value ?? "—"}{suffix}
      </p>
    </div>
  );
}

export default function RiskPage() {
  const [data, setData] = useState<RiskData | null>(null);
  const [loading, setLoading] = useState(true);
  const [regime, setRegime] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    api.portfolioRisk().then((d: unknown) => {
      setData(d as RiskData);
      setLoading(false);
    }).catch(() => setLoading(false));

    api.regime().then((d: unknown) => setRegime(d as Record<string, unknown>)).catch(() => {});
  }, []);

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">Risk Dashboard</h1>
      <p className="text-sm text-text-tertiary mb-8">Portfolio risk metrics, regime classification, and circuit breaker status.</p>

      {/* Regime */}
      {regime && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[11px] text-text-quaternary uppercase tracking-wider mb-1">Current Regime</p>
              <p className="text-lg font-semibold text-text-primary capitalize">{String(regime.current_regime || "unknown").replace("_", " ")}</p>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-text-quaternary">Confidence:</span>
              <span className="text-sm font-mono text-text-primary">{regime.confidence ? `${(Number(regime.confidence) * 100).toFixed(0)}%` : "—"}</span>
            </div>
          </div>
          {regime.probabilities ? (
            <div className="flex gap-3 mt-3">
              {Object.entries(regime.probabilities as Record<string, number>).map(([state, prob]) => (
                <div key={state} className="flex-1 rounded-lg bg-bg-primary p-2 text-center">
                  <p className="text-[10px] text-text-quaternary capitalize">{state.replace("_", " ")}</p>
                  <p className="text-sm font-mono text-text-primary">{(Number(prob) * 100).toFixed(0)}%</p>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-text-quaternary">Loading risk data...</p>
      ) : data?.error ? (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
          <p className="text-sm text-text-tertiary">{data.error}</p>
          <p className="text-xs text-text-quaternary mt-2">
            Risk metrics require open positions. Run an analysis, then click "Take Trade"
            on a trade idea to start building your portfolio.
          </p>
        </div>
      ) : data ? (
        <>
          {/* Key metrics */}
          <div className="grid grid-cols-4 gap-3 mb-6">
            <StatCard label="VaR (95%)" value={data.var_pct != null ? `${data.var_pct}` : null} color="text-signal-red" suffix="%" />
            <StatCard label="CVaR (95%)" value={data.cvar_pct != null ? `${data.cvar_pct}` : null} color="text-signal-red" suffix="%" />
            <StatCard label="Annual Vol" value={data.portfolio_vol_annual != null ? `${data.portfolio_vol_annual}` : null} suffix="%" />
            <StatCard label="Positions" value={String(data.positions_count)} />
          </div>

          {/* Circuit breaker */}
          {data.circuit_breaker && (
            <div className={`rounded-xl border p-4 mb-6 ${
              data.circuit_breaker.color === "green" ? "border-signal-green/20 bg-signal-green/[0.04]" :
              data.circuit_breaker.color === "yellow" ? "border-signal-yellow/20 bg-signal-yellow/[0.04]" :
              "border-signal-red/20 bg-signal-red/[0.04]"
            }`}>
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${
                  data.circuit_breaker.color === "green" ? "bg-signal-green" :
                  data.circuit_breaker.color === "yellow" ? "bg-signal-yellow" : "bg-signal-red"
                }`} />
                <span className="text-[13px] font-medium text-text-primary capitalize">{data.circuit_breaker.status}</span>
              </div>
              <p className="text-xs text-text-tertiary mt-1">{data.circuit_breaker.action}</p>
            </div>
          )}

          {/* Sector exposure */}
          {data.sector_exposure && Object.keys(data.sector_exposure.sector_breakdown || {}).length > 0 && (
            <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
              <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">Sector Exposure</h3>
              <div className="space-y-2">
                {Object.entries(data.sector_exposure.sector_breakdown).sort((a, b) => b[1] - a[1]).map(([sector, pct]) => (
                  <div key={sector} className="flex items-center gap-3">
                    <span className="text-xs text-text-secondary w-32 truncate">{sector}</span>
                    <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden">
                      <div className={`h-full rounded-full ${pct > 30 ? "bg-signal-red" : "bg-accent"}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                    <span className="text-xs font-mono text-text-primary w-10 text-right">{pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Correlation matrix */}
          {data.correlation_matrix && data.correlation_matrix.matrix?.length > 1 && (
            <CorrelationHeatmap tickers={data.correlation_matrix.tickers} matrix={data.correlation_matrix.matrix} />
          )}
        </>
      ) : null}
    </div>
  );
}
