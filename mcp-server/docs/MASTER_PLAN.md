# AlphaEngine — Master Plan

> **The single source of truth for the whole build.** Consolidates the product
> vision, the marketing reposition, the architecture, and the ordered build
> punch-list into one file. Everything else is history; build against this.
>
> Status: planned. No product code/copy written yet — awaiting greenlight.

---

# PART I — THE VISION

## Infrastructure, not an app

**AlphaEngine is the research-to-signal layer between a trader's data and their
execution algo.**

Every systematic trader — solo or fund — rebuilds the same plumbing: wrangle
data, compute signals, check for overfitting, gate for risk, generate ideas,
format the result for execution. That plumbing is undifferentiated heavy
lifting, and most people do the validation badly or not at all. AlphaEngine is
the stateless layer that does it once, correctly, for everyone:

> **Your data in. Validated, cited, risk-checked, algo-ready signals out. Nothing stored.**

Mental model to repeat: **"the signal infrastructure layer."** Not a dashboard
you log into — a primitive you build on. Less "research SaaS," more "the
deterministic computation + validation layer your algo calls before it trades."

### What "infrastructure" forces us to be
- **Programmable** — callable by an agent (MCP) *and* a plain execution bot (HTTP/JSON). No human in the path.
- **Deterministic** — same input, same output, version-pinned.
- **Composable** — tools chain; the agent desk orchestrates them into a slate.
- **Observable** — usage, latency, verification quality visible. Status page like real infra.
- **Secure** — stateless, no data sourced, no payloads stored. The trust posture *is* the product.
- **Consumable two ways** — machine-readable for the algo, human-readable for the desk.

### The two planes (the whole architecture)

```
                         ┌─────────────────────────────────────┐
   your licensed data ──▶│            ONE CORE ENGINE           │
                         │        (deterministic quant_core)    │
                         └───────────────┬─────────────────────┘
                          ┌──────────────┴───────────────┐
                          ▼                               ▼
              DETERMINISTIC PLANE              PROBABILISTIC PLANE
            (the algo's path)                 (the human's path)
       direct HTTP/JSON + MCP tools        agent desk: research / risk / CIO
       exact, reproducible, version-pinned reasons, narrates, generates ideas
                          │                               │
                          ▼                               ▼
          algo-ready signal envelope         cited slate in the secure desk UI
          (feeds execution directly)         (analyst reads, signs off)

            both emit the SAME SignalEnvelope · nothing retained
```

**The invariant that makes this real:** the LLM **never computes a number the
algo consumes.** An execution algo consumes the deterministic plane; agents are
for idea generation/research with a human in the loop. Same engine, two faces.
This is what makes "feeds seamlessly into a trading algo" true instead of a slogan.

### Two personas, one product

| | **Solo / systematic trader** | **Fund** |
|---|---|---|
| Wants | Cheap, self-serve, wire it into my bot | Infra behind my stack; trust posture |
| Path | MCP + direct API; desk UI as a bonus | API/MCP as infra; desk UI for analysts |
| Buys on | "It plugs into my algo and tells me when it's noise" | "Stateless, traceable, we never touch our data" |

---

# PART II — LOCKED DECISIONS

| # | Decision | Choice |
|---|----------|--------|
| 1 | Architecture | **Two planes / dual surface: MCP + deterministic REST** over one core |
| 2 | Marketing gating | **Public marketing + docs; gated app.** Demo runs on sample data, no account |
| 3 | SignalEnvelope ground truth | **Base v1 on the existing `IntelligenceMemo`/`TradeIdea` schema** (the real slate the system already emits); refine to v1.1 after first live run |
| 4 | Versioning | **Semver from first beta** (cheap now, expensive to retrofit) |
| 5 | MCP architecture | **Gateway over the INTACT backend** (no rewrite) + a data-injection seam |
| 6 | Repo layout | **`mcp-server/` subdir** as a Railway service |
| 7 | Demo data | **yfinance** (free, non-commercial → demo/eval only; never paid-customer-driven) |

**Why decision 3 this way:** the backend already produces a genuine slate
(`IntelligenceMemo` + `TradeIdea[]` carrying conviction/validation, `coverage`,
`citation_index`, provenance/lineage). That *is* the real artifact — design the
envelope against it (ground-truthed, no hand-authored sample needed); add only
the infra fields the memo schema lacks (`schema_version`, `engine_version`,
`determinism`, structured `validation` verdict).

---

# PART III — ARCHITECTURE

## Gateway over the intact backend (agent-to-agent)

The MCP server is a **thin gateway in front of the existing backend**, not a
fork. The flow is agent-to-agent: the fund's agent + their licensed data → over
MCP/HTTPS → our agent desk + quant engine → results back. We never *source*
data; the fund supplies it, we compute, we discard.

```
  Fund's agent (their LLM) + their licensed data   │   Execution bot + their data
            │ (MCP / HTTPS)                          │ (REST / HTTPS, no LLM)
            ▼                                         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  AlphaEngine gateway  —  auth (per-client key) · routing      │  ← new, thin
  ├──────────────────────────────────────────────────────────────┤
  │  DATA-INJECTION SEAM  ("data provided" mode)                  │  ← the core build
  ├──────────────────────────────────────────────────────────────┤
  │  EXISTING BACKEND, UNCHANGED                                  │
  │   • agent desk (research / risk / CIO …)  [probabilistic]     │
  │   • quant_core (pairs, factors, risk, deflated SR …) [det.]   │
  └──────────────────────────────────────────────────────────────┘
            │  SignalEnvelope (same shape from both planes)
            ▼   nothing stored
```

Three layers:
1. **Gateway** — FastMCP HTTP (`server.py`) + deterministic REST (`api.py`), per-client key auth, routing. Both thin adapters over one core.
2. **Data-injection seam** — *the core build.* Backend agents/quant currently
   FETCH (FRED/yfinance/SEC). Add a **"data provided" mode**: data arrives in the
   call payload; the orchestrator/agents/quant read from it; the data layer is
   never called. No-data principle holds. Add an input path; tear nothing out.
3. **Engine** — the existing agent desk + `quant_core`, unchanged.

## The Signal Envelope (the #1 product artifact)

Per-tool outputs are plumbing; the **single, stable, versioned envelope** is the
interface consumers build against. Both planes emit it. Design it first.

```
SignalEnvelope {
  schema_version: "1.0.0"            // semver; consumers pin
  engine_version: "..."             // which quant_core produced it (reproducibility)
  request_id: "..."                 // idempotency / tracing
  generated_at: ISO8601
  determinism: "exact" | "agent"    // which plane produced this

  signals: [{
    idea_id
    instruments: [{ symbol, side: long|short, weight?, hedge_ratio? }]
    thesis            // agent plane; null on raw deterministic
    levels:  { entry?, stop?, target? }
    sizing:  { suggested_weight?, var_contribution?, regime_multiplier? }
    validation: {     // THE MOAT, structural
      deflated_sharpe?, pbo?, psr?, n_trials?,
      verdict: "edge" | "inconclusive" | "likely_noise"
    }
    risk:    { var?, cvar?, factor_betas?, stress?, gate: pass|warn|block }
    context: { regime?, regime_posterior? }
    provenance: [{ field, tool, inputs_hash, formula }]
  }]
  warnings: [ ... ]                  // caps hit, short windows, fallbacks used
}
```

Rules that make it infrastructure:
- **Semver'd**; breaking change bumps major; 90-day deprecation window.
- **`engine_version` on every response** so an algo can reproduce or refuse.
- **No `verdict: "edge"` without `validation` populated** — the envelope
  structurally refuses to ship an idea it hasn't checked for overfitting.
- **Same shape from both planes** (deterministic: `thesis: null`). Algo ignores
  prose; desk renders it.

## Infra guarantees
- **Pin every numerical dep** (numpy/scipy/statsmodels/scikit-learn/hmmlearn) exactly — a minor bump can change a regression tail → a signal.
- **Golden-output tests** — frozen input→output per deterministic tool; CI fails on drift.
- **`engine_version` stamped** on every envelope.
- **LLM barred from the deterministic plane** — architectural invariant, not convention.
- **Structured error taxonomy** — `INPUT_TOO_LARGE`, `INSUFFICIENT_OBSERVATIONS`, `SCHEMA_INVALID`, `AUTH_*` — machine-parseable, not prose.
- **No-data-true telemetry** — log shapes/sizes/latency, never payload values.

## Tool taxonomy (the desk orchestrates these)

| Layer | Tools | Role | Beta? |
|---|---|---|---|
| **Signals** | cointegrated pairs, spread signal, ADF | generate candidate ideas | ✅ (pairs, spread) |
| **Validation** | deflated Sharpe, PBO/CSCV, purged CV, bootstrap CI, signal IC | gate for noise | ✅ (DSR, PBO) |
| **Risk** | VaR/CVaR, covariance shrinkage, correlation, stress, factor decomposition | gate sizing/exposure | ✅ (VaR/CVaR, factor) |
| **Construction** | Black-Litterman, HRP, mean-variance | ideas → weights | v2 |
| **Context** | regime classify, yield-curve analytics | condition everything | v2 |

Validation is a **gate, not a tool**: the desk auto-runs it before stamping any
idea `edge`; the envelope rejects `edge` without it. Rigor is default.

---

# PART IV — BUILD PUNCH-LIST (ordered)

Each step ends green (tests + verify) before the next. 1–6 = server foundation;
7–10 = productization.

1. **`quant_core/` extraction (6-tool beta cut) + golden-output fixtures + pinned deps.**
   Pairs, spread (Signals) · deflated Sharpe, PBO/CSCV (Validation) · VaR/CVaR,
   factor decomposition (Risk). Pure functions over supplied data. Freeze
   input→output fixtures; CI fails on drift. *(Math already verified largely
   pure/array-level — this is the fast path.)*
2. **`SignalEnvelope` v1 (Pydantic) + inbound data-contract schemas.** Mapped from
   existing memo/trade-idea fields + infra fields. Hard input validation, clear
   schema errors. Rule: no `verdict: edge` without `validation`.
3. **`api.py` — deterministic REST.** POST data → envelope, no LLM. The algo's door.
4. **`server.py` — FastMCP HTTP tools** over the same core. The agent's door.
5. **Data-injection seam.** Backend agent desk "data-provided" mode → validated,
   risk-gated slate → envelope. **Test that no data fetch fires.**
6. **Validation gate.** Desk auto-runs deflated-SR / PBO; envelope rejects `edge`
   without `validation`.
7. **Per-client key auth** (`AUTH_STUB` local) shared by REST + MCP.
8. **Structured error taxonomy + `request_id` echo.**
9. **Clerk → key provisioning + connection-snippet dashboard** (MCP status UI:
   connection/key, usage by tool, latency/error, output quality; stateless metrics).
10. **No-data-safe telemetry** + public status page.

**v2 (not now):** data-by-reference (large universes); universe-scale screening;
Construction (BL/HRP/MVO) + Context (regime/curve) tools; full 25-tool catalog.

---

# PART V — MARKETING PUNCH-LIST (ordered)

Public per decision 2; same institutional design system. The page sells *engine
+ memo* today; reposition to *infrastructure + algo-ready signal*.

1. **Hero rewrite** → "The signal layer between your data and your algo" + infra
   sub-copy. **+ JSON/memo split tearsheet** (same result as human memo *and* as
   a SignalEnvelope JSON; caption "human-readable for your desk, machine-readable
   for your algo, same result, same receipts"). *Highest-leverage single change.*
2. **`05 / OUTPUT` showcase card** — "Signals your algo can consume" (the envelope).
3. **"How it works"** section — the two-planes pipeline on one screen.
4. **TopNav** → `PRODUCT · HOW IT WORKS · DOCS · TRUST · PRICING`.
5. **SourceLedger** copy extension — validator refuses to ship an *idea it can't
   validate* (rigor), not just a figure it can't trace (provenance).
6. **Two-door CTA** — primary "Read the docs / Connect the MCP", secondary "Open
   the desk / Try the live demo".
7. **Public docs page** — one real request → envelope example (REST + MCP).
8. **Pricing placeholder** — "In beta — join the beta / talk to us."
9. **IntelligenceLayer** reframe → the two-planes story (not "two engines merge").
10. **StatusStrip** — at least one stat speaks to infra reliability
    (deterministic · version-pinned / latency once the status page exists).
11. **"Built on MCP"** note — MCP-native is a distribution surface + credibility signal.
12. **White-label** section — engine/desk under a partner's brand *(copy pending CEO call: day-one vs contact-us).*

**Keep verbatim:** TaglineStrip "NO DATA, BY DESIGN / Your data goes in. The math
comes out. Nothing stays." — best line on the page.

**Flow:** app stays gated; add the **integration onboarding branch** — first
question "How will you use AlphaEngine?" → [wire into my algo] / [use the desk] /
[both]. The wire-in path → provision key → connection snippet (MCP URL + key) →
"your first call" doc → copy-paste example returning an envelope. **Demo without
signup** (sample data, eval-labeled). Activation metric = **time-to-first-signal**.

---

# PART VI — CROSS-CUTTING INVARIANTS (never violate)

- **No data sourced or stored.** Stateless; telemetry never logs values.
- **Determinism on the algo plane** — pinned deps, golden tests, `engine_version` stamped, LLM barred.
- **Versioned contract** — semver on API + envelope; 90-day deprecation window.
- **Validator gates rigor + provenance** — both, by default.
- **Backend stays intact** — add an input path + gateway; tear nothing out.

---

# PART VII — SEQUENCING & OPEN INPUTS

**On greenlight, default order:** Build steps **1–2 first** (quant_core + golden
tests, then SignalEnvelope v1) — the foundation REST/MCP/tearsheet/docs all
depend on. Marketing track can run in parallel **once the envelope shape is
pinned** (step 2), since the tearsheet + docs must show the real envelope.

**Open CEO inputs (non-blocking for planning; needed before the noted step):**
- **Pricing model** (per-seat / per-call / enterprise) — before marketing step 8 ships real copy.
- **White-label** — day-one messaging vs "contact us" — before marketing step 12.
- **App gating style** — open sign-up vs invite-only waitlist (marketing is public either way).
- **Legal sign-off** on no-data / eval framing — before charging.

---

# RISKS / FLAGS

- **Dependency drift breaks determinism** → pin exact + golden tests. Highest-priority infra risk.
- **LLM nondeterminism leaks onto the algo path** → planes stay separate; agents never compute consumed numbers.
- **Inline size limits** → demo on small universes; `# TODO(v2): data-by-reference`; warn, don't truncate.
- **Schema churn pre-1.0** → expected in beta; version from first release so consumers aren't surprised.
- **Legal** → no-data / eval framing blessed by counsel before charging (cheap consult, litigated area).
