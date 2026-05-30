/**
 * Canonical SignalEnvelope v1 sample — the single source the marketing
 * tearsheet and the public /docs page both render, so "human-readable for your
 * desk, machine-readable for your algo" is literally the same object shown two
 * ways. Mirrors mcp-server/docs/SIGNAL_ENVELOPE.md (the pinned shape) and the
 * backend IntelligenceMemo it projects from.
 *
 * Not fetched at runtime — it's marketing copy / a docs fixture. The real
 * envelope is emitted by the gateway (build steps T3+).
 */

export interface SignalEnvelope {
  schema_version: string;
  engine_version: string;
  request_id: string;
  generated_at: string;
  determinism: "exact" | "agent";
  signals: EnvelopeSignal[];
  warnings: string[];
}

export interface EnvelopeSignal {
  idea_id: string;
  instruments: { symbol: string; side: "long" | "short"; weight?: number; hedge_ratio?: number }[];
  thesis: string | null;
  levels: { entry?: number; stop?: number; target?: number };
  sizing: { suggested_weight?: number; var_contribution?: number; regime_multiplier?: number };
  validation: {
    deflated_sharpe?: number;
    pbo?: number;
    psr?: number;
    n_trials?: number;
    verdict: "edge" | "inconclusive" | "likely_noise";
  };
  risk: {
    var?: number;
    cvar?: number;
    factor_betas?: Record<string, number>;
    stress?: Record<string, number>;
    gate: "pass" | "warn" | "block";
  };
  context: { regime?: string; regime_posterior?: Record<string, number> };
  falsification_criteria: string[];
  mandate_warnings: string[];
  provenance: { field: string; tool: string; inputs_hash: string; formula: string }[];
}

/**
 * The human-readable view of the SAME result — what the desk UI renders as a
 * memo. The tearsheet shows this beside the JSON below.
 */
export const sampleMemo = {
  title: "Under-covered industrials into the reopening",
  decision: "GO" as const,
  conviction: 82,
  regime: "EXPANSION",
  risk: "ELEVATED",
  sources: 22,
  deflated_sharpe: 0.91,
  rows: [
    { t: "ASLE", d: "LONG", c: 84, e: "12.40", s: "10.90", p: "17.20", verdict: "edge" as const },
    { t: "WNC", d: "LONG", c: 78, e: "26.10", s: "23.40", p: "33.50", verdict: "edge" as const },
    { t: "TGLS", d: "LONG", c: 71, e: "58.30", s: "52.00", p: "72.00", verdict: "inconclusive" as const },
  ],
};

export const sampleEnvelope: SignalEnvelope = {
  schema_version: "1.0.0",
  engine_version: "quant_core@1.0.0",
  request_id: "req_8f3a1c0e",
  generated_at: "2026-05-30T18:22:04Z",
  determinism: "agent",
  signals: [
    {
      idea_id: "asle-outright-01",
      instruments: [{ symbol: "ASLE", side: "long", weight: 0.05 }],
      thesis:
        "Aftermarket parts demand is inflecting as carriers defer fleet renewal; ASLE trades at 6.1x EV/EBITDA vs a 9.4x peer median with insider cluster buying in the last 30 days.",
      levels: { entry: 12.4, stop: 10.9, target: 17.2 },
      sizing: { suggested_weight: 0.05, var_contribution: 0.011, regime_multiplier: 1.0 },
      validation: { deflated_sharpe: 0.91, pbo: 0.18, psr: 0.86, n_trials: 240, verdict: "edge" },
      risk: {
        var: 0.021,
        cvar: 0.034,
        factor_betas: { mkt: 1.18, smb: 0.62, hml: 0.31 },
        stress: { "rates_+100bp": -0.04, "oil_-20pct": 0.02 },
        gate: "pass",
      },
      context: {
        regime: "expansion",
        regime_posterior: { risk_on: 0.61, late_cycle: 0.24, transition: 0.1, risk_off: 0.05 },
      },
      falsification_criteria: [
        "Aftermarket revenue decelerates QoQ for two consecutive quarters",
        "Insider cluster reverses to net selling",
      ],
      mandate_warnings: [],
      provenance: [
        {
          field: "validation.deflated_sharpe",
          tool: "quant.overfitting.deflated_sharpe_ratio",
          inputs_hash: "sha256:3b1f…",
          formula: "DSR = Φ((SR − SR0)·√(n−1) / √(1 − γ3·SR + (γ4−1)/4·SR²))",
        },
        { field: "levels.entry", tool: "client.supplied_quote", inputs_hash: "sha256:9ad2…", formula: "last_trade" },
        {
          field: "risk.gate",
          tool: "agents.desk5_decision_gate.compute_decision",
          inputs_hash: "sha256:c44e…",
          formula: "GO if top_conviction≥75 ∧ risk≠extreme ∧ regime_aligned",
        },
      ],
    },
    {
      idea_id: "wnc-tgls-pair-01",
      instruments: [
        { symbol: "WNC", side: "long", hedge_ratio: 1.0 },
        { symbol: "TGLS", side: "short", hedge_ratio: 0.84 },
      ],
      thesis: null,
      levels: { entry: 1.42, stop: 1.31, target: 1.66 },
      sizing: { suggested_weight: 0.04, var_contribution: 0.006 },
      validation: { deflated_sharpe: 0.12, pbo: 0.57, psr: 0.41, n_trials: 240, verdict: "likely_noise" },
      risk: { var: 0.009, cvar: 0.014, factor_betas: { mkt: 0.06 }, gate: "block" },
      context: { regime: "expansion" },
      falsification_criteria: ["Spread half-life exceeds the holding horizon"],
      mandate_warnings: [],
      provenance: [
        {
          field: "validation.pbo",
          tool: "quant.overfitting.pbo_cscv",
          inputs_hash: "sha256:71b9…",
          formula: "PBO = P(rank_OOS > median | rank_IS = best)",
        },
        {
          field: "instruments.hedge_ratio",
          tool: "quant.pairs.analyze_pair",
          inputs_hash: "sha256:0c2d…",
          formula: "TLS β on log-prices",
        },
      ],
    },
  ],
  warnings: [
    "TGLS price history is 142 observations — below the 250-obs window for a stable cointegration estimate",
  ],
};

/** Pretty-printed JSON string for verbatim display in the tearsheet / docs. */
export const sampleEnvelopeJson = JSON.stringify(sampleEnvelope, null, 2);
