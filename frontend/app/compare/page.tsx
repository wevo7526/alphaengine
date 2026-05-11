"use client";

import { useState } from "react";
import { api } from "@/lib/api";

interface MarketResp {
  fundamentals?: {
    pe_ratio: number | null;
    forward_pe: number | null;
    pb_ratio: number | null;
    ev_ebitda: number | null;
    market_cap: number | null;
    revenue_growth: number | null;
    profit_margin: number | null;
    debt_to_equity: number | null;
    free_cash_flow: number | null;
    dividend_yield: number | null;
    beta: number | null;
    "52w_high": number | null;
    "52w_low": number | null;
    short_ratio: number | null;
    sector: string | null;
    industry: string | null;
    current_price: number | null;
  };
  price_history?: Array<{ date: string; close: number }>;
}

interface FactorBetas {
  market?: number | null;
  size?: number | null;
  value?: number | null;
  profitability?: number | null;
  low_vol?: number | null;
  momentum?: number | null;
  [k: string]: number | null | undefined;
}

interface AlphaVsFactor {
  factor_share: number | null;
  alpha_share: number | null;
  unexplained_share: number | null;
  factor_share_pct: number | null;
  alpha_share_pct: number | null;
  residual_vol_annual_pct: number | null;
  alpha_annualized_pct: number | null;
  idiosyncratic_sharpe: number | null;
  interpretation: string | null;
  model: string | null;
}

interface FactorResp {
  tickers: string[];
  model: string;
  alpha?: number | null;
  beta?: number | null;
  r_squared?: number | null;
  multi_factor?: {
    alpha: number | null;
    factor_betas: FactorBetas;
    factor_tstats?: Record<string, number | null>;
    r_squared: number | null;
    n_observations: number;
    model: string;
    multicollinearity_flag?: boolean;
    high_vif_factors?: string[];
  };
  alpha_vs_factor?: AlphaVsFactor;
  alpha_vs_factor_per_ticker?: Record<string, AlphaVsFactor>;
}

interface ScenarioBreakdown {
  ticker: string;
  weight_pct: number;
  direction: string;
  betas: Record<string, number | null>;
  n_obs: number;
  contributions_by_axis: Record<string, number>;
  projected_position_return_pct: number;
  position_pnl_pct: number;
}

interface ScenarioResp {
  shock_inputs: Record<string, number>;
  expected_proxy_returns: Record<string, number>;
  portfolio_pnl_pct: number;
  portfolio_pnl_dollars: number;
  breakdown: ScenarioBreakdown[];
  beta_method: string;
  history_period: string;
  n_positions: number;
  error?: string;
}

function compactMarketCap(v: number | null | undefined): string | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toFixed(0)}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  return `${v.toFixed(digits)}%`;
}

function fmtPctDecimal(v: number | null | undefined, digits = 1): string | null {
  // For values stored as decimals (0.05 = 5%)
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 2): string | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  return v.toFixed(digits);
}

function Row({
  label,
  a,
  b,
  hint,
}: {
  label: string;
  a: string | null;
  b: string | null;
  hint?: string;
}) {
  return (
    <tr className="border-t border-border-primary">
      <td className="py-1.5 text-[12px] text-text-tertiary" title={hint}>
        {label}
      </td>
      <td className="py-1.5 text-[12px] font-mono text-text-primary text-right">
        {a ?? "—"}
      </td>
      <td className="py-1.5 text-[12px] font-mono text-text-primary text-right">
        {b ?? "—"}
      </td>
    </tr>
  );
}

export default function ComparePage() {
  const [tickerA, setTickerA] = useState("");
  const [tickerB, setTickerB] = useState("");
  const [marketA, setMarketA] = useState<MarketResp | null>(null);
  const [marketB, setMarketB] = useState<MarketResp | null>(null);
  const [factors, setFactors] = useState<FactorResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Scenario state
  const [shock, setShock] = useState({
    rates_shock_bps: 0,
    credit_shock_bps: 0,
    oil_shock_pct: 0,
    gold_shock_pct: 0,
    fx_shock_pct: 0,
  });
  const [scenarioResult, setScenarioResult] = useState<ScenarioResp | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);

  async function runCompare() {
    const a = tickerA.trim().toUpperCase();
    const b = tickerB.trim().toUpperCase();
    if (!a || !b) {
      setError("Both ticker fields are required.");
      return;
    }
    if (a === b) {
      setError("Tickers must be different.");
      return;
    }
    setLoading(true);
    setError(null);
    setMarketA(null);
    setMarketB(null);
    setFactors(null);
    try {
      const [mA, mB, f] = await Promise.all([
        api.market(a, "6mo") as Promise<MarketResp>,
        api.market(b, "6mo") as Promise<MarketResp>,
        api.factors([a, b], "ff5_mom") as Promise<FactorResp>,
      ]);
      setMarketA(mA);
      setMarketB(mB);
      setFactors(f);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Compare failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function runScenario() {
    const a = tickerA.trim().toUpperCase();
    const b = tickerB.trim().toUpperCase();
    if (!a || !b) {
      setError("Run compare first — scenario needs both tickers loaded.");
      return;
    }
    setScenarioLoading(true);
    setError(null);
    try {
      // Use equal-weight long/long positions to focus on relative scenario sensitivity
      const positions = [
        { ticker: a, size_pct: 50, direction: "bullish" },
        { ticker: b, size_pct: 50, direction: "bullish" },
      ];
      const res = (await api.customScenario(shock, positions)) as ScenarioResp;
      setScenarioResult(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Scenario failed";
      setError(msg);
    } finally {
      setScenarioLoading(false);
    }
  }

  const fA = marketA?.fundamentals;
  const fB = marketB?.fundamentals;

  const factorA = factors?.alpha_vs_factor_per_ticker?.[tickerA.toUpperCase()];
  const factorB = factors?.alpha_vs_factor_per_ticker?.[tickerB.toUpperCase()];
  const betas = factors?.multi_factor?.factor_betas;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Compare</h1>
        <p className="text-[12px] text-text-tertiary mt-1">
          Side-by-side fundamentals + factor exposure + risk. Then dial in a
          custom macro shock and see projected per-position P&L using empirically
          fit cross-asset betas.
        </p>
      </div>

      {/* Ticker inputs */}
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="text-[11px] text-text-quaternary uppercase tracking-wider block mb-1">
            Ticker A
          </label>
          <input
            type="text"
            value={tickerA}
            onChange={(e) => setTickerA(e.target.value.toUpperCase())}
            placeholder="e.g. AAPL"
            className="w-full bg-bg-surface border border-border-primary rounded-lg px-3 py-2 text-[13px] text-text-primary font-mono focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex-1">
          <label className="text-[11px] text-text-quaternary uppercase tracking-wider block mb-1">
            Ticker B
          </label>
          <input
            type="text"
            value={tickerB}
            onChange={(e) => setTickerB(e.target.value.toUpperCase())}
            placeholder="e.g. MSFT"
            className="w-full bg-bg-surface border border-border-primary rounded-lg px-3 py-2 text-[13px] text-text-primary font-mono focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <button
          onClick={runCompare}
          disabled={loading || !tickerA || !tickerB}
          className="rounded-lg px-4 py-2 text-[12px] font-medium bg-white/[0.07] hover:bg-white/[0.12] text-text-primary border border-border-primary disabled:opacity-50"
        >
          {loading ? "Loading…" : "Compare"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-signal-red/40 bg-signal-red/10 p-3 text-[12px] text-signal-red">
          {error}
        </div>
      )}

      {/* Comparison panels */}
      {(fA || fB) && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
          <h2 className="text-[13px] font-medium text-text-primary mb-3">
            Fundamentals
          </h2>
          <table className="w-full">
            <thead>
              <tr className="text-text-quaternary">
                <th className="font-normal text-left text-[11px] uppercase tracking-wider pb-2">
                  Metric
                </th>
                <th className="font-normal text-right text-[12px] pb-2 text-text-primary">
                  {tickerA.toUpperCase()}
                </th>
                <th className="font-normal text-right text-[12px] pb-2 text-text-primary">
                  {tickerB.toUpperCase()}
                </th>
              </tr>
            </thead>
            <tbody>
              <Row label="Price" a={fA?.current_price !== null && fA?.current_price !== undefined ? `$${fA.current_price.toFixed(2)}` : null}
                   b={fB?.current_price !== null && fB?.current_price !== undefined ? `$${fB.current_price.toFixed(2)}` : null} />
              <Row label="Market cap" a={compactMarketCap(fA?.market_cap)} b={compactMarketCap(fB?.market_cap)} />
              <Row label="Sector" a={fA?.sector ?? null} b={fB?.sector ?? null} />
              <Row label="P/E (trailing)" a={fmtNum(fA?.pe_ratio)} b={fmtNum(fB?.pe_ratio)}
                   hint="Trailing 12-month price-to-earnings ratio" />
              <Row label="P/E (forward)" a={fmtNum(fA?.forward_pe)} b={fmtNum(fB?.forward_pe)}
                   hint="Forward 12-month P/E based on analyst estimates" />
              <Row label="EV / EBITDA" a={fmtNum(fA?.ev_ebitda)} b={fmtNum(fB?.ev_ebitda)}
                   hint="Enterprise value to EBITDA — capital-structure-neutral valuation" />
              <Row label="P/B" a={fmtNum(fA?.pb_ratio)} b={fmtNum(fB?.pb_ratio)} />
              <Row label="Revenue growth" a={fmtPctDecimal(fA?.revenue_growth)} b={fmtPctDecimal(fB?.revenue_growth)} />
              <Row label="Profit margin" a={fmtPctDecimal(fA?.profit_margin)} b={fmtPctDecimal(fB?.profit_margin)} />
              <Row label="Debt / equity" a={fmtNum(fA?.debt_to_equity)} b={fmtNum(fB?.debt_to_equity)} />
              <Row label="Dividend yield" a={fmtPctDecimal(fA?.dividend_yield)} b={fmtPctDecimal(fB?.dividend_yield)} />
              <Row label="Beta (yfinance)" a={fmtNum(fA?.beta)} b={fmtNum(fB?.beta)} />
              <Row label="52w high" a={fA?.["52w_high"] !== null && fA?.["52w_high"] !== undefined ? `$${fA["52w_high"].toFixed(2)}` : null}
                   b={fB?.["52w_high"] !== null && fB?.["52w_high"] !== undefined ? `$${fB["52w_high"].toFixed(2)}` : null} />
              <Row label="52w low" a={fA?.["52w_low"] !== null && fA?.["52w_low"] !== undefined ? `$${fA["52w_low"].toFixed(2)}` : null}
                   b={fB?.["52w_low"] !== null && fB?.["52w_low"] !== undefined ? `$${fB["52w_low"].toFixed(2)}` : null} />
              <Row label="Short ratio" a={fmtNum(fA?.short_ratio)} b={fmtNum(fB?.short_ratio)}
                   hint="Days-to-cover; >5 indicates meaningful short interest" />
            </tbody>
          </table>
        </div>
      )}

      {factors && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
          <h2 className="text-[13px] font-medium text-text-primary mb-1">
            Factor Exposure
          </h2>
          <p className="text-[11px] text-text-tertiary mb-3">
            Variance-decomposition of each name's return into factor-driven vs
            idiosyncratic. Portfolio-level betas reported from joint FF5-style +
            Low-Vol + Momentum regression.{" "}
            {factors.multi_factor?.multicollinearity_flag && (
              <span className="text-signal-yellow">
                Multicollinearity flagged on:{" "}
                {factors.multi_factor.high_vif_factors?.join(", ")}
              </span>
            )}
          </p>
          <table className="w-full">
            <thead>
              <tr className="text-text-quaternary">
                <th className="font-normal text-left text-[11px] uppercase tracking-wider pb-2">
                  Metric
                </th>
                <th className="font-normal text-right text-[12px] pb-2 text-text-primary">
                  {tickerA.toUpperCase()}
                </th>
                <th className="font-normal text-right text-[12px] pb-2 text-text-primary">
                  {tickerB.toUpperCase()}
                </th>
              </tr>
            </thead>
            <tbody>
              <Row label="Alpha annualized %" a={fmtPct(factorA?.alpha_annualized_pct)}
                   b={fmtPct(factorB?.alpha_annualized_pct)}
                   hint="Annualized OLS intercept after FF5-style + Low-Vol + Momentum factors" />
              <Row label="Idiosyncratic Sharpe" a={fmtNum(factorA?.idiosyncratic_sharpe)}
                   b={fmtNum(factorB?.idiosyncratic_sharpe)}
                   hint="Information ratio of the alpha leg — alpha_annual / residual_vol_annual" />
              <Row label="Factor share %" a={fmtPct(factorA?.factor_share_pct)}
                   b={fmtPct(factorB?.factor_share_pct)}
                   hint="Variance share explained by factor exposure" />
              <Row label="Alpha share %" a={fmtPct(factorA?.alpha_share_pct)}
                   b={fmtPct(factorB?.alpha_share_pct)}
                   hint="Idiosyncratic variance share (true alpha component)" />
              <Row label="Residual vol annual %" a={fmtPct(factorA?.residual_vol_annual_pct)}
                   b={fmtPct(factorB?.residual_vol_annual_pct)} />
              <Row label="Interpretation" a={factorA?.interpretation ?? null}
                   b={factorB?.interpretation ?? null}
                   hint="factor_driven (>70% factor) | idiosyncratic (>70% alpha) | mixed" />
            </tbody>
          </table>

          {betas && (
            <div className="mt-4 pt-3 border-t border-border-primary">
              <p className="text-[11px] text-text-quaternary uppercase tracking-wider mb-2">
                Portfolio-level factor betas (equal-weighted)
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2 text-[11px]">
                {Object.entries(betas).map(([k, v]) => {
                  const t = factors.multi_factor?.factor_tstats?.[k];
                  return (
                    <div key={k} className="rounded-lg border border-border-primary bg-bg-primary p-2">
                      <p className="text-text-quaternary uppercase tracking-wider">{k}</p>
                      <p className="font-mono text-text-primary">{fmtNum(v) ?? "—"}</p>
                      {t !== undefined && t !== null && (
                        <p className={`text-[10px] font-mono ${Math.abs(t) >= 2 ? "text-signal-green" : "text-text-tertiary"}`}>
                          t={fmtNum(t, 1)}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Scenario dials */}
      {(fA || fB) && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-4">
          <h2 className="text-[13px] font-medium text-text-primary mb-1">
            Custom Macro Scenario
          </h2>
          <p className="text-[11px] text-text-tertiary mb-4">
            Empirical per-ticker betas to each axis are fit at request time from 1y daily
            history — no hardcoded sector tables. Equal-weighted long/long pair used to
            isolate relative sensitivity.
          </p>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
            {[
              { key: "rates_shock_bps", label: "Rates Δbp (10Y)", step: 25, min: -200, max: 200 },
              { key: "credit_shock_bps", label: "Credit Δbp (HY)", step: 25, min: -200, max: 500 },
              { key: "oil_shock_pct", label: "Oil Δ%", step: 5, min: -50, max: 100 },
              { key: "gold_shock_pct", label: "Gold Δ%", step: 5, min: -30, max: 30 },
              { key: "fx_shock_pct", label: "USD (DXY) Δ%", step: 1, min: -15, max: 15 },
            ].map(({ key, label, step, min, max }) => (
              <div key={key} className="space-y-1">
                <label className="text-[10px] text-text-quaternary uppercase tracking-wider block">
                  {label}
                </label>
                <input
                  type="number"
                  step={step}
                  min={min}
                  max={max}
                  value={shock[key as keyof typeof shock]}
                  onChange={(e) =>
                    setShock({ ...shock, [key]: Number(e.target.value) || 0 })
                  }
                  className="w-full bg-bg-primary border border-border-primary rounded-lg px-2 py-1.5 text-[13px] text-text-primary font-mono focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
            ))}
          </div>

          <button
            onClick={runScenario}
            disabled={scenarioLoading || !tickerA || !tickerB}
            className="rounded-lg px-4 py-2 text-[12px] font-medium bg-white/[0.07] hover:bg-white/[0.12] text-text-primary border border-border-primary disabled:opacity-50"
          >
            {scenarioLoading ? "Running…" : "Project P&L"}
          </button>

          {scenarioResult && !scenarioResult.error && (
            <div className="mt-4 pt-4 border-t border-border-primary space-y-3">
              <div className="flex items-baseline gap-4">
                <div>
                  <p className="text-[11px] text-text-quaternary uppercase tracking-wider">
                    Portfolio P&L (equal-weighted)
                  </p>
                  <p
                    className={`text-2xl font-mono font-medium ${
                      scenarioResult.portfolio_pnl_pct >= 0
                        ? "text-signal-green"
                        : "text-signal-red"
                    }`}
                  >
                    {scenarioResult.portfolio_pnl_pct >= 0 ? "+" : ""}
                    {scenarioResult.portfolio_pnl_pct.toFixed(2)}%
                  </p>
                </div>
                <div className="text-[11px] text-text-tertiary">
                  {scenarioResult.beta_method} · {scenarioResult.history_period} history
                </div>
              </div>

              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-text-quaternary">
                    <th className="font-normal text-left pb-2">Ticker</th>
                    <th className="font-normal text-right pb-2">β rates</th>
                    <th className="font-normal text-right pb-2">β credit</th>
                    <th className="font-normal text-right pb-2">β oil</th>
                    <th className="font-normal text-right pb-2">β gold</th>
                    <th className="font-normal text-right pb-2">β fx</th>
                    <th className="font-normal text-right pb-2">Projected %</th>
                  </tr>
                </thead>
                <tbody>
                  {scenarioResult.breakdown.map((p) => (
                    <tr key={p.ticker} className="border-t border-border-primary">
                      <td className="py-1.5 font-medium text-text-primary">{p.ticker}</td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">
                        {fmtNum(p.betas.rates, 3) ?? "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">
                        {fmtNum(p.betas.credit, 3) ?? "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">
                        {fmtNum(p.betas.oil, 3) ?? "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">
                        {fmtNum(p.betas.gold, 3) ?? "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">
                        {fmtNum(p.betas.fx, 3) ?? "—"}
                      </td>
                      <td
                        className={`py-1.5 text-right font-mono ${
                          p.projected_position_return_pct >= 0
                            ? "text-signal-green"
                            : "text-signal-red"
                        }`}
                      >
                        {p.projected_position_return_pct >= 0 ? "+" : ""}
                        {p.projected_position_return_pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="text-[10px] text-text-quaternary">
                Expected proxy moves —
                TLT {scenarioResult.expected_proxy_returns.TLT_pct >= 0 ? "+" : ""}
                {scenarioResult.expected_proxy_returns.TLT_pct.toFixed(2)}%,{" "}
                HYG {scenarioResult.expected_proxy_returns.HYG_pct >= 0 ? "+" : ""}
                {scenarioResult.expected_proxy_returns.HYG_pct.toFixed(2)}%,{" "}
                USO {scenarioResult.expected_proxy_returns.USO_pct >= 0 ? "+" : ""}
                {scenarioResult.expected_proxy_returns.USO_pct.toFixed(2)}%,{" "}
                GLD {scenarioResult.expected_proxy_returns.GLD_pct >= 0 ? "+" : ""}
                {scenarioResult.expected_proxy_returns.GLD_pct.toFixed(2)}%,{" "}
                UUP {scenarioResult.expected_proxy_returns.UUP_pct >= 0 ? "+" : ""}
                {scenarioResult.expected_proxy_returns.UUP_pct.toFixed(2)}%
              </div>
            </div>
          )}

          {scenarioResult?.error && (
            <div className="mt-3 rounded-lg border border-signal-red/40 bg-signal-red/10 p-3 text-[12px] text-signal-red">
              {scenarioResult.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
