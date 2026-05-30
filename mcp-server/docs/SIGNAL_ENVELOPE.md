# SignalEnvelope v1 — the contract

> The single, semver'd output artifact emitted by **both** planes (deterministic
> REST and the agent desk). Consumers build against this, not against per-tool
> shapes. Design it once; pin it; never break it without a major bump + a 90-day
> deprecation window.
>
> Status: **shape pinned** (this doc). Pydantic models land in build step T3.
> The marketing tearsheet and the public docs page render the canonical example
> below — it is the real shape, ground-truthed against the backend's
> `IntelligenceMemo` / `TradeIdea` schema.

---

## 1. Why one envelope

Per-tool outputs are plumbing. The envelope is the **interface**. An execution
bot pins `schema_version`, reads `signals[].instruments` + `levels` + `sizing` +
`validation.verdict` + `risk.gate`, and ignores `thesis`. A human desk renders
the same object as a memo. Same bytes, two readers.

Both planes emit it:
- **Deterministic plane** (`api.py`, sync): `determinism: "exact"`, `thesis: null`.
- **Agent plane** (the desk, async job): `determinism: "agent"`, `thesis` populated.

---

## 2. The schema (v1)

```
SignalEnvelope {
  schema_version: "1.0.0"            // semver; consumers pin. Major bump = breaking.
  engine_version: string             // e.g. "quant_core@1.0.0" — reproducibility / refuse-on-mismatch
  request_id: string                 // tracing + idempotency echo
  generated_at: string               // ISO-8601 UTC
  determinism: "exact" | "agent"     // which plane produced this

  signals: Signal[]
  warnings: string[]                 // caps hit, short windows, fallbacks used — never silent
}

Signal {
  idea_id: string
  instruments: Instrument[]
  thesis: string | null              // agent plane only; null on the deterministic plane
  levels:  { entry?: number, stop?: number, target?: number }
  sizing:  { suggested_weight?: number, var_contribution?: number, regime_multiplier?: number }
  validation: Validation             // THE MOAT — structural, never omitted on an "edge"
  risk:    Risk
  context: { regime?: string, regime_posterior?: Record<string, number> }
  falsification_criteria: string[]   // "what would prove this wrong" — from the memo
  mandate_warnings: string[]         // surfaced, not hidden — from the memo
  provenance: Provenance[]
}

Instrument { symbol: string, side: "long" | "short", weight?: number, hedge_ratio?: number }

Validation {
  deflated_sharpe?: number
  pbo?: number                       // probability of backtest overfitting (0..1)
  psr?: number                       // probabilistic Sharpe ratio (0..1)
  n_trials?: number
  verdict: "edge" | "inconclusive" | "likely_noise"
}

Risk {
  var?: number
  cvar?: number
  factor_betas?: Record<string, number>
  stress?: Record<string, number>
  gate: "pass" | "warn" | "block"    // populated by the existing Decision Gate (compute_decision)
}

Provenance { field: string, tool: string, inputs_hash: string, formula: string }
```

### The one structural rule (unit-tested)
> A `Signal` with `validation.verdict == "edge"` is **rejected** unless
> `validation` carries at least one populated rigor figure (`deflated_sharpe`,
> `pbo`, or `psr`). The envelope structurally refuses to ship an idea it has not
> checked for overfitting. `inconclusive` / `likely_noise` may ship with sparse
> validation (that *is* the finding).

---

## 3. Mapping from the existing backend (ground truth)

The backend already emits a genuine `IntelligenceMemo` carrying everything but the
infra fields. The envelope is a projection of it — no new analysis, just a remap.

| Envelope field | Source in `IntelligenceMemo` / `TradeIdea` |
|---|---|
| `schema_version` | constant `"1.0.0"` |
| `engine_version` | gateway constant, stamped from the pinned `quant_core` build |
| `request_id` | gateway-generated; echoed from the inbound request |
| `generated_at` | `memo.timestamp` |
| `determinism` | `"agent"` for the desk; `"exact"` for `api.py` |
| `signals[].idea_id` | stable hash of `TradeIdea.ticker` + `structure_type` (+ index) |
| `instruments[].symbol` | `TradeIdea.ticker` (+ `pair_short_leg` as a second leg) |
| `instruments[].side` | `TradeIdea.direction` → long/short (bullish→long, bearish→short) |
| `instruments[].hedge_ratio` | pair hedge ratio when `structure_type == "pair"` |
| `thesis` | `TradeIdea.thesis` (agent plane); `null` on deterministic |
| `levels.entry/stop/target` | `entry_zone` (parsed) / `stop_loss` / `take_profit` |
| `sizing.suggested_weight` | `TradeIdea.position_size_pct` |
| `sizing.regime_multiplier` | `regime_conditional_size_pct` ÷ `position_size_pct` |
| `sizing.var_contribution` | from `quant/risk.compute_marginal_var` (deterministic plane) |
| `validation.deflated_sharpe` | `quant/overfitting.deflated_sharpe_ratio` |
| `validation.pbo` | `quant/overfitting.pbo_cscv` |
| `validation.psr` | `quant/overfitting.probabilistic_sharpe_ratio` |
| `validation.n_trials` | trials passed to the deflated-SR computation |
| `validation.verdict` | derived: edge if DSR>0 & PBO low & PSR high; else inconclusive / likely_noise |
| `risk.var` / `cvar` | `quant/risk.compute_portfolio_var` / `compute_portfolio_cvar` |
| `risk.factor_betas` | `quant/factors.decompose_factors` (+ `TradeIdea.beta_to_spy`) |
| `risk.stress` | `quant/stress` macro-shock outputs |
| `risk.gate` | **`agents/desk5_decision_gate.compute_decision`** → GO→pass, WATCH→warn, NO-GO→block |
| `context.regime` | `memo.macro_regime` / `macro_context.current_regime` |
| `context.regime_posterior` | `quant/regime.classify_regime` posterior |
| `falsification_criteria` | `memo.falsification_criteria` |
| `mandate_warnings` | `memo.mandate_warnings` |
| `provenance` | `memo.lineage.sources` + `citation_index` (field → tool → inputs_hash → formula) |
| `warnings` | `data_quality` != complete, coverage gaps, pricing-prefetch timeouts, caps hit |

**Reuse, do not rebuild:** `risk.gate` comes straight from `compute_decision`
(GO/WATCH/NO-GO → pass/warn/block). The validation verdict is derived from the
existing `quant/overfitting` outputs. No gate, math, or memo schema is
reimplemented in the gateway.

---

## 4. Canonical example (agent plane)

This is the real shape, rendered on the marketing tearsheet and the docs page.
It mirrors the hero memo ("under-covered industrials"). The deterministic-plane
variant is identical with `determinism: "exact"` and every `thesis: null`.

```json
{
  "schema_version": "1.0.0",
  "engine_version": "quant_core@1.0.0",
  "request_id": "req_8f3a1c0e",
  "generated_at": "2026-05-30T18:22:04Z",
  "determinism": "agent",
  "signals": [
    {
      "idea_id": "asle-outright-01",
      "instruments": [{ "symbol": "ASLE", "side": "long", "weight": 0.05 }],
      "thesis": "Aftermarket parts demand is inflecting as carriers defer fleet renewal; ASLE trades at 6.1x EV/EBITDA vs a 9.4x peer median with insider cluster buying in the last 30 days.",
      "levels": { "entry": 12.40, "stop": 10.90, "target": 17.20 },
      "sizing": { "suggested_weight": 0.05, "var_contribution": 0.011, "regime_multiplier": 1.0 },
      "validation": {
        "deflated_sharpe": 0.91,
        "pbo": 0.18,
        "psr": 0.86,
        "n_trials": 240,
        "verdict": "edge"
      },
      "risk": {
        "var": 0.021,
        "cvar": 0.034,
        "factor_betas": { "mkt": 1.18, "smb": 0.62, "hml": 0.31 },
        "stress": { "rates_+100bp": -0.04, "oil_-20pct": 0.02 },
        "gate": "pass"
      },
      "context": {
        "regime": "expansion",
        "regime_posterior": { "risk_on": 0.61, "late_cycle": 0.24, "transition": 0.10, "risk_off": 0.05 }
      },
      "falsification_criteria": [
        "Aftermarket revenue decelerates QoQ for two consecutive quarters",
        "Insider cluster reverses to net selling"
      ],
      "mandate_warnings": [],
      "provenance": [
        { "field": "validation.deflated_sharpe", "tool": "quant.overfitting.deflated_sharpe_ratio", "inputs_hash": "sha256:3b1f…", "formula": "DSR = Φ((SR − SR0)·√(n−1) / √(1 − γ3·SR + (γ4−1)/4·SR²))" },
        { "field": "levels.entry", "tool": "client.supplied_quote", "inputs_hash": "sha256:9ad2…", "formula": "last_trade" },
        { "field": "risk.gate", "tool": "agents.desk5_decision_gate.compute_decision", "inputs_hash": "sha256:c44e…", "formula": "GO if top_conviction≥75 ∧ risk≠extreme ∧ regime_aligned" }
      ]
    },
    {
      "idea_id": "wnc-tgls-pair-01",
      "instruments": [
        { "symbol": "WNC",  "side": "long",  "hedge_ratio": 1.0 },
        { "symbol": "TGLS", "side": "short", "hedge_ratio": 0.84 }
      ],
      "thesis": null,
      "levels": { "entry": 1.42, "stop": 1.31, "target": 1.66 },
      "sizing": { "suggested_weight": 0.04, "var_contribution": 0.006 },
      "validation": {
        "deflated_sharpe": 0.12,
        "pbo": 0.57,
        "psr": 0.41,
        "n_trials": 240,
        "verdict": "likely_noise"
      },
      "risk": {
        "var": 0.009,
        "cvar": 0.014,
        "factor_betas": { "mkt": 0.06 },
        "gate": "block"
      },
      "context": { "regime": "expansion" },
      "falsification_criteria": ["Spread half-life exceeds the holding horizon"],
      "mandate_warnings": [],
      "provenance": [
        { "field": "validation.pbo", "tool": "quant.overfitting.pbo_cscv", "inputs_hash": "sha256:71b9…", "formula": "PBO = P(rank_OOS > median | rank_IS = best)" },
        { "field": "instruments.hedge_ratio", "tool": "quant.pairs.analyze_pair", "inputs_hash": "sha256:0c2d…", "formula": "TLS β on log-prices" }
      ]
    }
  ],
  "warnings": [
    "TGLS price history is 142 observations — below the 250-obs window for a stable cointegration estimate"
  ]
}
```

The second signal is deliberate: the system flagged **its own** pair idea as
`likely_noise` (PBO 0.57, DSR 0.12) and the Decision Gate `block`ed it. That
honesty — shipping the negative verdict instead of hiding it — is the brand.

---

## 5. Structured errors (companion contract)

Machine-parseable, never prose. Always echo `request_id`.

```
{ "error": { "code": "INSUFFICIENT_OBSERVATIONS", "message": "...", "request_id": "req_…" } }
```

Codes: `INPUT_TOO_LARGE`, `INSUFFICIENT_OBSERVATIONS`, `SCHEMA_INVALID`,
`AUTH_INVALID`, `AUTH_MISSING`, `QUOTA_EXCEEDED`, `JOB_NOT_FOUND`, `JOB_FAILED`.

---

## 6. Versioning policy

- Semver from this first beta. Additive fields → minor. Removals / type changes /
  semantic changes → major, with a 90-day deprecation window.
- `engine_version` is stamped on every envelope independently of `schema_version`
  so an algo can reproduce a result or refuse to act on an engine it hasn't pinned.
