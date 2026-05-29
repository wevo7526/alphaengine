# Alpha Engine — Build Plan: Provenance, NLP, and Quant Rigor

> **For the agent (Claude Code):** This is a phased spec, not a script. Do **Phase 0** before writing any code. Implement phases in order; do not start Phase 2 until Phase 1's "Definition of Done" passes. Adapt all module paths, language choices, and naming to the **existing repo conventions** — the layouts below are suggestions, not mandates. When a decision is ambiguous, prefer the smallest change that satisfies the acceptance criteria, and leave a `// TODO(alpha):` note rather than inventing scope.

---

## Context & guiding constraints

**What this is.** Alpha Engine is an agentic research desk for small/mid alternative managers: a natural-language query runs a pipeline (macro regime, fundamentals, options surface, correlation, risk) and produces a research memo with trade ideas, plus a paper-trading simulator that marks P&L against real prices. Human-in-the-loop; no auto-execution.

**Current stack (do not add paid services without a free tier).**
- LLM: Anthropic (Claude)
- Macro: FRED
- Prices/fundamentals: Yahoo Finance, Finnhub, Alpha Vantage
- News: NewsAPI
- Filings: SEC EDGAR via sec-api.io
- Web: Firecrawl
- DB: Postgres · Auth: Clerk · Env: Production (Railway)

**Hard constraint: ~$0 budget.** Every external call must be cached, rate-limited, and batched. Cost discipline is a first-class requirement, not an afterthought — see the **Cost Discipline** section, which Phases 1–3 all depend on.

**The architectural principle that governs every phase:**
> **Compute first. Narrate second. Validate third.** The LLM never *originates* a number. The deterministic engine computes every figure and binds it to a source; the LLM only arranges pre-computed, pre-sourced facts into prose and tags each claim with the IDs it used; a validator rejects any output containing a fact it cannot trace. Agents propose, math disposes, the human decides.

This single rule is what makes the product trustworthy to a sophisticated buyer. One hallucinated number ends the relationship.

---

## Phase 0 — Orient (do this first, then stop and report)

Before implementing anything, produce a short `docs/REPO_MAP.md` answering:

1. Where does **data fetching** live (one module per source? a shared client layer?), and how are responses currently stored/cached?
2. Where is the **memo generation** pipeline — the boundary between deterministic computation and the LLM call(s)?
3. Where do the **quant metrics** (VaR, Sharpe, correlation, HMM regime, options greeks) get computed, and in what language (Python service? TS?)?
4. What does the **Postgres schema** look like today? List tables touching memos, ideas, positions, and any cached source data.
5. How are **LLM calls** currently made (SDK, model, streaming, any caching/batching)?

Report this map and a one-paragraph implementation approach for Phase 1 **before** writing Phase 1 code.

---

## Phase 1 — Provenance & Citations (every output is traceable)

**Goal:** every quantitative claim and every qualitative assertion in a memo, trade idea, risk factor, and hedge recommendation is bound to a verifiable receipt. No naked numbers, no unsourced claims.

### 1.1 Two receipt types

- **Computed receipt** — a number produced by the engine (correlation, VaR, Sharpe, P/E, beta, IV skew, conviction sub-scores). Stores: the metric name, the computed value, the input series/identifiers, the formula/function reference, the upstream data source(s), and a UTC timestamp.
- **Source receipt** — a qualitative claim grounded in retrieved text (filing language, news, transcript passage). Stores: the source (URL or EDGAR accession no.), the exact extracted passage (verbatim, ≤ a few sentences), retrieval timestamp, and a content hash.

### 1.2 Data model (adapt to existing schema)

Add a provenance layer. Suggested tables:

- `evidence` — `id`, `kind` (`computed` | `source`), `created_at`, `source_name`, `source_ref` (URL/accession/endpoint), `passage` (nullable, for source), `metric` (nullable, for computed), `value_json` (nullable), `inputs_json` (nullable), `formula_ref` (nullable), `content_hash`.
- `claim_evidence` — join table: `claim_id` (or `memo_section_id` + offset), `evidence_id`. A claim may cite multiple evidence rows.
- Every fetch from FRED/Yahoo/Finnhub/AlphaVantage/NewsAPI/SEC/Firecrawl writes a row (or upserts by `content_hash`) so the same datum is never silently re-fetched (also serves the cost goal).

### 1.3 Pipeline change (the core of Phase 1)

Restructure memo generation into three explicit stages:

1. **Compute stage** — run all deterministic math and all text retrieval/extraction. Emit a **Fact Sheet**: a structured list of `evidence` rows, each with a stable `id`. This is the *only* factual material the LLM is allowed to use.
2. **Narration stage** — call the LLM with the Fact Sheet (IDs + values + passages) and instruct it to write the memo **using only Fact Sheet entries**, emitting inline citation markers (e.g. `[[ev:1234]]`) on every sentence that asserts a fact. Forbid introducing new numbers.
3. **Validation stage** — a deterministic linter parses the generated memo and:
   - extracts every numeric token and every factual sentence;
   - verifies each maps to a cited, existing `evidence.id`;
   - flags **orphans** (numbers/claims with no citation) and **dangling refs** (citations to nonexistent evidence);
   - **hard-fails the memo** if any orphan numeric token exists. Either auto-repair (re-prompt with the specific orphan) or refuse to publish and surface the gap.

### 1.4 Rendering

- In the UI and the PDF, render citation markers as hoverable/clickable "receipts" that reveal the underlying value, source, and timestamp. This *is* the "full source lineage" promise made real — it is also a sales asset, so make it visible, not buried.
- The exported PDF must include an appendix mapping every receipt ID to its source.

### 1.5 Definition of Done (Phase 1)

- [ ] A generated memo cannot ship with a single uncited number (validator enforces, with a test that injects a hallucinated figure and confirms the pipeline rejects it).
- [ ] Every trade-idea field (entry/stop/target, R/R, beta, size) traces to a computed receipt with a named formula.
- [ ] Every Key Finding and Risk Factor sentence carries ≥1 citation.
- [ ] Receipts are clickable in the UI and present in the PDF appendix.
- [ ] Re-running the same query reuses cached evidence by `content_hash` (no duplicate paid calls).

---

## Phase 2 — Make NLP Earn Its Keep

**Goal:** prove the LLM is doing *real analytical work* on real text from **SEC EDGAR** and **Firecrawl**, producing structured signals that (a) are grounded in cited passages (Phase 1) and (b) measurably move outputs. No NLP theater.

### 2.1 SEC EDGAR — use it for the signal it's actually good for

The highest-value, well-documented text signal is **filing change** ("Lazy Prices," Cohen/Malloy/Nguyen): year-over-year *changes* in 10-K/10-Q language (esp. Risk Factors and MD&A) predict negative forward returns; the market underreacts. Build:

- **2.1a Filing ingestion.** For each covered ticker, pull the latest 10-K/10-Q/8-K and the prior comparable filing. **Cost note:** sec-api.io has a thin free tier — prefer hitting **SEC EDGAR directly** (`data.sec.gov`, EDGAR full-text search, and the submissions JSON API) which is free; keep sec-api.io as a fallback. Respect SEC's fair-access rate limits and declare a proper `User-Agent`.
- **2.1b Section extraction.** Parse out Risk Factors (Item 1A) and MD&A (Item 7 / 2). Normalize whitespace/boilerplate.
- **2.1c Change scoring (deterministic + NLP).** Compute a `filing_change_score` per name: a cheap deterministic baseline (cosine similarity on TF-IDF or simple n-gram Jaccard between this filing's section and the prior one) **plus** an LLM pass that *categorizes* the material changes (new/removed risk factors, sentiment shift, hedging language) and returns a structured summary with the exact changed passages as source receipts. Large change → bearish tilt input to conviction.
- **2.1d 8-K novelty.** Flag 8-Ks whose content is unusual vs. the company's recent cadence; surface as event receipts.

### 2.2 Firecrawl — real NLP, not a glorified fetch

Use Firecrawl for text NLP can't get cheaply elsewhere, then run structured extraction:

- **2.2a Earnings-call transcripts** (and IR pages). Extract: management tone, uncertainty/hedging language, Q&A evasiveness, and **tone delta vs. the prior call**. Output structured scores + the passages they're derived from.
- **2.2b Targeted news/commentary** beyond NewsAPI headlines — full-article context for the names in the slate, deduped against what NewsAPI already returned.
- **Discipline:** Firecrawl free tier is small. Only crawl names that reach the memo stage; cache by URL + content hash; never re-crawl within a TTL.

### 2.3 The NLP→signal contract (this is what "doing work" means)

Every NLP pass must emit a **typed signal object**, not prose:
```
{ ticker, signal_name, value (numeric/score), direction, confidence,
  evidence_ids[], model, generated_at }
```
These signals (filing_change, call_tone, news_sentiment, revision_momentum if available via Finnhub estimates) feed the conviction model **deterministically** (Phase 3.4). The raw passages become source receipts (Phase 1). The LLM extracts and classifies; it does not decide weights.

### 2.4 Prove it (the verification the user asked for)

Build a diagnostic harness, `scripts/nlp_audit`:

- **Attribution view:** for any memo, show each NLP signal, its source passages, and its numeric contribution to each conviction score. If a signal contributes 0 everywhere, it's theater — flag it.
- **Ablation test:** run the pipeline with NLP signals on vs. zeroed-out; assert conviction rankings *change* in sensible, logged ways. A diff of "no change" means NLP isn't wired in.
- **Sanity fixtures:** golden-file tests on 3–5 known filings (e.g. a filing with a large, real risk-factor change) where the expected `filing_change_score` direction is asserted.
- **Coverage metric:** % of memo names that actually received a fresh filing/transcript pass vs. fell back to price-only. Track and surface it.

### 2.5 Definition of Done (Phase 2)

- [ ] EDGAR pulled directly (free path) with caching; a real 10-K vs prior 10-K diff produces a scored, passage-cited change object.
- [ ] Firecrawl produces ≥1 transcript-derived signal with cited passages for covered names.
- [ ] Every NLP output is a typed signal with `evidence_ids`, consumed deterministically downstream.
- [ ] `nlp_audit` ablation proves NLP signals move conviction; coverage % is reported per memo.

---

## Phase 3 — Quant Rigor + Extras

**Goal:** the deterministic spine becomes the part a quant respects. Priority order matters — 3.1 first, because without it everything else surfaces noise.

### 3.1 Anti-overfitting layer (highest leverage; also the moat)

Most "AI finds alpha" tools never address multiple-hypothesis overfitting and therefore surface noise. This layer is also your differentiator — it ties to the receipts theme: *"we tell you when an idea is probably noise."*

- **Hypothesis ledger.** Record *every* idea/config the agent generates per run, not just survivors. The denominator (number of trials) is required input for the stats below.
- **Deflated Sharpe Ratio** (Bailey & López de Prado): adjust Sharpe for number of trials and for skew/kurtosis. Display deflated, never raw, Sharpe on any backtest.
- **Probability of Backtest Overfitting (PBO)** via Combinatorially Symmetric Cross-Validation (CSCV).
- **Purged + embargoed k-fold / combinatorial purged CV** for any train/test split on overlapping-label financial data (prevents leakage that fakes good results).
- Implement from the published formulas (they're public). You already bootstrap VaR — reuse that machinery for bootstrapped Sharpe confidence intervals and the CSCV resampling.

### 3.2 Portfolio construction upgrades

Naive sample covariance is unstable exactly where weights are sensitive. Use **PyPortfolioOpt** (free, MIT) which implements all three:

- **Ledoit-Wolf covariance shrinkage** before any optimization (`risk_models.CovarianceShrinkage`).
- **Hierarchical Risk Parity** (`HRPOpt`) — robust, no matrix inversion, visualizes well in the existing correlation UI.
- **Black-Litterman** (`BlackLittermanModel`) — *prioritize this*: it's the principled bridge from agent output to weights. Map each trade idea's thesis → a BL **view**, and its conviction score → **view confidence (omega)**. This replaces the ad-hoc "4.0% / 3.5%" sizing with defensible, decomposable weights.

### 3.3 Honest simulator (make the track record bulletproof)

The forward, out-of-sample track record is the single most credible sales asset — it answers the "did the tool cause returns?" objection. Two requirements:

- **Transaction cost + slippage + capacity modeling** on every simulated fill. An equity curve without costs lies.
- **Point-in-time / look-ahead guard:** ideas must be timestamped before the price action they're judged on; add an assertion that no idea is scored against data predating its `generated_at`. Make the track record tamper-evident (append-only, hashed).

### 3.4 Conviction calibration loop

- Make `conviction` a **deterministic, decomposable composite** of sub-scores (factor, revision momentum, filing_change, call_tone, options positioning, regime fit) with explicit weights — not an LLM mood score. Each sub-score is a receipt.
- Log conviction vs. realized outcome from the simulator. Compute **calibration (reliability curve) and Brier score** over time; expose a "calibration" panel. Re-weight sub-scores periodically based on realized predictive value. This closes the loop and compounds into a moat.

### 3.5 Regime-conditional factor tilting

Connect the existing HMM regime posterior to signal weighting: value/momentum/quality/low-vol pay off differently by regime. Use the regime probabilities to tilt factor weights rather than running them static. Cheap, defensible, uses machinery you already have.

### 3.6 Extra ideas (backlog, not required for DoD)

- **Options-implied signals** as first-class inputs (vol-risk-premium, skew-as-positioning) — you already surface the surface; turn it into scored signals.
- **PEAD / estimate-revision momentum** via Finnhub estimates (robust documented anomaly, cheap).
- **Cross-sectional ranking** with a heavily-regularized gradient-boosted model over the signal panel — validated only with 3.1's purged CV.
- **Memo "confidence downgrade"** when coverage % (Phase 2.4) or evidence freshness is low — honesty as a feature.

### 3.7 Definition of Done (Phase 3)

- [ ] No backtest displays raw Sharpe; deflated Sharpe + PBO shown, hypothesis ledger populated.
- [ ] Weights come from BL/HRP on shrunk covariance, with per-idea view→weight traceability.
- [ ] Simulator applies costs and enforces the look-ahead guard.
- [ ] Conviction is decomposable into receipted sub-scores; calibration panel renders against the live track record.

---

## Cross-cutting: Cost Discipline (required for all phases)

Verified current Anthropic levers — use them aggressively on the NLP load:

- **Batch API:** flat **50% off input *and* output**, async (≤24h), up to 100K requests/batch, every model. Route **all bulk NLP** (filing diffs, transcript scoring across the universe) through Batch — it's non-urgent by nature.
- **Prompt caching:** cache reads cost **~10% of input** (90% off); writes cost 1.25× (5-min TTL) or 2× (1-hr). Cache the **extraction schema/instructions and any large static context** so every per-name call reads the cache. Stacks with Batch for **~95% total savings**.
- **Model tiering:** bulk extraction/classification → **Haiku 4.5** ($1/$5 per M tok). Final memo synthesis → **Sonnet 4.6** ($3/$15) or **Opus** ($5/$25) only where reasoning quality justifies it. Don't synthesize memos on Opus by default.

General frugality (every external source):
- Cache-by-content-hash everything; never re-fetch within TTL (this is shared with the Phase 1 evidence store — one mechanism, two wins).
- Respect free-tier rate limits explicitly: Alpha Vantage (~5/min, ~25/day), Finnhub free tier, NewsAPI, Firecrawl, SEC fair-access. Add a per-source rate limiter and a daily budget guard that degrades gracefully (price-only memo with a logged "coverage low" flag) rather than erroring.
- Only run expensive NLP on names that reach the memo stage, never the whole screen.

---

## Verification & test strategy (applies throughout)

- **Hallucination regression test:** inject a fabricated figure into the narration stage; assert the validator rejects the memo (Phase 1 guard must never silently pass).
- **Golden filings:** fixtures for filing-diff direction (Phase 2).
- **Ablation test:** NLP-on vs NLP-off changes rankings (Phase 2).
- **Leakage test:** an idea scored against pre-`generated_at` data must raise (Phase 3.3).
- **Determinism test:** same inputs → same computed receipts (the math must be reproducible even though the prose isn't).
- Keep a `docs/CHANGELOG_BUILD.md` noting what each phase changed and why, for the audit story.

---

## Suggested module layout (adapt to repo)

```
/provenance        # evidence store, content-hashing, citation linter
/pipeline
  compute.py       # stage 1: all math + retrieval → Fact Sheet
  narrate.py       # stage 2: LLM writes from Fact Sheet only
  validate.py      # stage 3: orphan/dangling-ref linter (hard gate)
/nlp
  edgar.py         # direct EDGAR client + section parse + filing diff
  firecrawl.py     # transcript/news crawl + cache
  signals.py       # typed NLP→signal contract
/quant
  overfitting.py   # deflated Sharpe, PBO/CSCV, purged CV, hypothesis ledger
  portfolio.py     # Ledoit-Wolf, HRP, Black-Litterman (PyPortfolioOpt)
  sim.py           # costs, slippage, look-ahead guard, track record
  conviction.py    # decomposable composite + calibration loop
  regime.py        # HMM posterior → factor tilts
/llm
  client.py        # model tiering, Batch API, prompt caching
/scripts
  nlp_audit/       # attribution, ablation, coverage diagnostics
/docs
  REPO_MAP.md  CHANGELOG_BUILD.md
```

---

## Build order (do not skip the gates)

1. **Phase 0** report → confirm approach.
2. **Phase 1** provenance + citation gate → DoD must pass.
3. **Phase 2** EDGAR + Firecrawl NLP wired through the signal contract → DoD must pass.
4. **Phase 3** in sub-order **3.1 → 3.2 → 3.3 → 3.4 → 3.5**, then backlog 3.6.

The through-line: defensibility is not "we found alpha." It's *"the rigorous, auditable, agent-native research desk that harvests documented edges across more names than a small desk can cover — and tells you when you're fooling yourself."* Phases 1–3 build exactly that, in priority order.
