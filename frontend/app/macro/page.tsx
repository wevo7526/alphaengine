"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { MacroChart } from "@/components/MacroChart";
import type { MacroIndicator } from "@/lib/types";

function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) return process.env.NEXT_PUBLIC_BACKEND_URL;
  if (typeof window !== "undefined" && window.location.hostname.includes("railway.app"))
    return "https://alpha-backend-production-51df.up.railway.app";
  return "http://localhost:8000";
}
const API_BASE = getApiBase();

const LABELS: Record<string, string> = {
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

interface MacroSeries {
  yield_curve: { date: string; value: number }[];
  vix: { date: string; value: number }[];
  credit_spreads: { date: string; value: number }[];
  fed_funds: { date: string; value: number }[];
}

export default function MacroPage() {
  const [indicators, setIndicators] = useState<Record<string, MacroIndicator>>({});
  const [series, setSeries] = useState<MacroSeries | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.macro().then((d: unknown) => {
        if (cancelled) return;
        const data = d as { indicators: Record<string, MacroIndicator> };
        setIndicators(data.indicators);
      }),
      fetch(`${API_BASE}/api/quant/macro-series`)
        .then((r) => {
          if (!r.ok) return null;
          return r.json();
        })
        .then((d: MacroSeries | null) => {
          if (cancelled || !d) return;
          setSeries(d);
        })
        .catch(() => {}),
    ]).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="p-8">
        <div className="text-sm text-text-quaternary">Loading macro data...</div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
        Macro Dashboard
      </h1>
      <p className="text-sm text-text-tertiary mb-8">
        Real-time economic indicators and regime signals.
      </p>

      {/* Charts — the important visualizations */}
      {series && (
        <div className="grid grid-cols-2 gap-4 mb-8">
          <MacroChart
            title="Yield Curve (10Y-2Y)"
            data={series.yield_curve}
            color="#3b82f6"
            unit="%"
          />
          <MacroChart
            title="VIX"
            data={series.vix}
            color="#ef4444"
            invertColor
          />
          <MacroChart
            title="HY Credit Spreads"
            data={series.credit_spreads}
            color="#f59e0b"
            unit="%"
            invertColor
          />
          <MacroChart
            title="Fed Funds Rate"
            data={series.fed_funds}
            color="#8b5cf6"
            unit="%"
          />
        </div>
      )}

      {/* All readings — compact list */}
      <div className="rounded-xl border border-border-primary bg-bg-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-border-primary">
          <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider">
            Current Readings
          </h2>
        </div>
        <div className="divide-y divide-border-primary">
          {Object.entries(indicators).map(([key, ind]) => {
            const label = LABELS[key] ?? key;
            const positive = ind.change > 0;
            return (
              <div
                key={key}
                className="flex items-center justify-between px-4 py-2.5"
              >
                <span className="text-[13px] text-text-secondary">{label}</span>
                <div className="flex items-center gap-3">
                  <span
                    className={`text-[11px] font-mono ${positive ? "text-signal-green" : "text-signal-red"}`}
                  >
                    {positive ? "+" : ""}{ind.change.toFixed(2)}
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
    </div>
  );
}
