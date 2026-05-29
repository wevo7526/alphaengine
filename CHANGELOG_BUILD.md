# CHANGELOG_BUILD.md

Per-phase record of what the Build Plan work changed and why (audit story).

---

## Phase 0 — Orient (complete)

- Added [REPO_MAP.md](REPO_MAP.md): answers the five orientation questions and
  records the per-phase readiness picture (Phase 1 ~60% scaffolded, Phase 2
  ~25%, Phase 3 ~50%, Cost Discipline 0%).
- Confirmed Phase 1 approach with the user: **hard-fail + auto-repair**
  validator, **Postgres evidence tables now**, **cost levers folded into
  Phase 1**.

## Phase 1 — Provenance & Citations (in progress)

**Deterministic core — built and verified (no LLM/API calls needed to test):**

- **Evidence store** (`backend/provenance/`): `EvidenceRecord` +
  `ClaimEvidenceRecord` ORM models (`db/models.py`); `store.py` with
  content-hash receipt builders (`computed_receipt`, `source_receipt`), a
  `FactSheet` container that dedups by hash and assigns stable `[[ev:n]]` ids;
  `repository.py` with `upsert_many` (content-hash dedup = persistent cache,
  no duplicate paid calls), `link_claims`, `get_for_memo`.
  - *Verified:* hash determinism (float-jitter collapses), dedup, cache-reuse
    (re-running the same query returns identical evidence ids), claim linking.
  - *Why:* satisfies Build Plan §1.1/§1.2 and the Cost Discipline content-hash
    cache in one mechanism.

- **LLM cost layer** (`backend/llm/`): tiered `get_llm(tier)` factory
  (`extraction`=Haiku / `synthesis`=Sonnet / `heavy`=Opus, env-overridable in
  `config.py`); `cache_system_block` applies Anthropic ephemeral prompt caching
  to large static system prompts. `base_agent` delegates to it (default tier =
  historically-pinned Sonnet, so existing behavior is unchanged) and now wraps
  each agent's system prompt in a cache block. Per-agent `llm_tier` knob added.
  - *Verified:* agent import graph intact, default model unchanged, tiers
    resolve to distinct model ids.

- **Validator** (`backend/pipeline/validate.py`): `validate_memo(prose,
  fact_sheet)` flags **orphans** (uncited, unmatched numbers → hard fail),
  **dangling** citations (→ hard fail), and **mismatches** (cited but wrong
  value → warning). Numeric extraction mirrors `base_agent._ground_check`.
  - *Verified:* a correctly-cited memo passes; an injected hallucinated figure
    is rejected (the Build Plan §1.5 regression guard, in unit form).

- **Compute stage** (`backend/pipeline/compute.py`): `build_fact_sheet(...)`
  harvests receipts from the desks' existing outputs — trade-idea numeric
  fields (entry/stop/target/R-R/size/conviction/beta, each with a named
  formula ref), macro indicators + regime, live prices, and lineage sources.
  - *Verified:* end-to-end with the validator on a synthetic desk state.

**Live memo path — wired (settings-flagged, reversible):**

- **C-wire** (`agents/orchestrator.py`, `agents/cio_synthesizer.py`,
  `main.py`): the synthesizer now runs the three stages —
  *compute* (`build_fact_sheet` from macro/regime, live prices, trade-idea
  fields, lineage) → *narrate* (Fact Sheet block + `[[ev:n]]` guidance fed to
  the CIO) → *validate* (`validate_against_fact_sheet`; on orphan/dangling, one
  **auto-repair** re-prompt, then `finalize_with_evidence` rewrites `[[ev:n]]`
  to numbered `[N]` footnotes continuing after the existing source citations,
  extends `citation_index`, downgrades `verification_status` to `unverified`
  if the gap persists). `main.py` upserts evidence receipts (content-hash
  deduped) and links each cited claim to its evidence row once the memo id
  exists. Guarded by `PROVENANCE_PIPELINE` / `PROVENANCE_AUTO_REPAIR`
  (default on); legacy `[[src:...]]` citation path still runs underneath.
  - *Note:* `[[ev:n]]` citations are OPTIONAL-but-encouraged in the prompt
    (avoids the empty-output regression CLAUDE.md records); the post-processor
    backfills footnotes and the gate surfaces gaps rather than 500-ing.

- **E** — evidence footnotes flow through the existing `citation_index`, so
  the in-app `CitationIndexPanel` renders them with no frontend change.
  Computed receipts encode the value in the footnote label ("VIX = 25.78") and
  the **named formula** in `source_id`; source receipts carry the verbatim
  passage as the excerpt. PDF `_citation_index_block` enriched to print the
  formula/accession + excerpt — the receipt appendix the DoD requires.

- **F** — `backend/tests/` pytest suite (14 tests, all green):
  `test_validate.py` (incl. the hallucination-injection regression),
  `test_provenance.py` (determinism, dedup, content-hash cache reuse, claim
  links), `test_pipeline.py` (Fact Sheet harvest, footnote finalize, receipt
  label). Added `pytest` + `pytest-asyncio` to requirements; `pytest.ini`
  with `asyncio_mode=auto`.

**Cost Discipline:** model tiering (`extraction`/`synthesis`/`heavy`,
env-overridable) + ephemeral prompt caching on agent system prompts are live
via `backend/llm/`; default tier keeps the historically-pinned Sonnet so
existing behavior is unchanged. Bulk-extraction agents opt in via
`llm_tier = "extraction"` (ready for Phase 2's filing/transcript load).

**Phase 1 DoD status:** validator rejects uncited numbers (test-proven);
trade-idea fields trace to named-formula computed receipts; evidence receipts
are clickable in UI + present in the PDF appendix; re-running a query reuses
evidence by content_hash (test-proven). Remaining for full live confidence: a
real end-to-end run against the LLM/data APIs (not exercised here to conserve
rate limits) and the "every Key Finding / Risk Factor sentence carries ≥1
citation" coverage target, which depends on live narrator citation behavior.

**Local dev note:** backend deps install into `backend/.venv` (was not
present); used for all verification runs above. `alphaengine.db` is a transient
SQLite test artifact (gitignored).

## Phase 2 — Make NLP Earn Its Keep (complete; gated OFF by default)

**Cost posture (per user direction):** use **sec-api.io** (existing key, ~31
free calls left), NOT direct EDGAR. **Firecrawl does the heavy fetching** —
it scrapes the *public* filing HTML so section extraction comes off sec-api
entirely (and Firecrawl's own infra sidesteps the SEC User-Agent concern).
sec-api is used for exactly **one listing call per ticker** (the reliable
latest/prior pairing) and as an extraction fallback. The Phase-1 **evidence
store doubles as a permanent per-filing cache** (filings are immutable), so a
section costs one fetch ever. A `SecBudget` hard ceiling (`SEC_CALL_BUDGET`,
default 25) and `FILING_NLP_MAX_NAMES` bound spend. **All filing/transcript
NLP defaults OFF** (`FILING_NLP_ENABLED`, `TRANSCRIPT_NLP_ENABLED`) so dev
never touches the quota; flip on for a real run.

- **2.3 signal contract** (`agents/nlp/signals.py`): `NLPSignal`
  {ticker, signal_name, value, direction, confidence, evidence_ids, model,
  generated_at, detail} + `aggregate_nlp_tilt` / `tilt_by_ticker` — the
  **deterministic** fold into a conviction tilt (the LLM never sets weights).
- **2.1c filing diff** (`agents/nlp/filing_diff.py`): deterministic
  `filing_change_score` (TF cosine + n-gram Jaccard + sentence-level
  add/remove diff) → magnitude bucket; optional **Haiku** change
  categorization (extraction tier + prompt cache); `build_filing_signal`
  emits a bearish-by-default (Lazy Prices) signal + changed-passage source
  receipts.
- **2.1b section parser** (`agents/nlp/sections.py`): pulls Item 1A / Item 7
  (10-K) / Item 2 (10-Q) out of scraped markdown, skipping the table of
  contents (longest start→end span wins).
- **2.1a ingest** (`agents/nlp/filing_ingest.py`): Firecrawl-first with
  evidence-cache → Firecrawl scrape+parse → sec-api fallback; `SecBudget`
  meters every live call; fully injectable (tests use fakes, zero network).
- **2.2 transcripts** (`agents/nlp/transcripts.py`): Firecrawl-only fetch +
  deterministic tone / hedging-uncertainty / Q&A-evasiveness scoring (reuses
  the VADER+lexicon sentiment) + tone-delta vs prior call → `call_tone`
  signal with hedged-sentence receipts.
- **2.1d 8-K novelty** (`agents/nlp/events_novelty.py`): item-code rarity vs
  recent cadence (listing-metadata only, no extraction) → `event_novelty`
  signal; restatement/impairment items read bearish.
- **Wiring** (`agents/nlp/runner.py`, `orchestrator.py`, `pipeline/compute.py`,
  `main.py`): the strategy node gathers signals for capped memo-stage names
  and `apply_nlp_tilt_to_ideas` **nudges each trade idea's conviction**
  deterministically with a logged `nlp_adjustment` receipt; changed-passage
  receipts thread into the Fact Sheet (small excerpts only — full sections are
  persistence-only), NLP coverage % lands under `memo.coverage.nlp`, and
  evidence + section caches persist via the Phase-1 store.
- **2.4 nlp_audit** (`scripts/nlp_audit/`): `attribution_report` (per-signal
  contribution + theater flags for signals that contribute 0 everywhere),
  `ablation_report` (conviction rankings NLP-ON vs zeroed — proves NLP moves
  conviction), `coverage_report`. Runnable via `python -m scripts.nlp_audit`.

**Tests:** `backend/tests/test_nlp.py` (12 tests) + golden filing fixtures
(`tests/fixtures/filing_1A_{prior,current}.txt`, a real material-weakness /
going-concern change). Full suite now **26/26 green**, no live calls:
filing-diff golden direction, section parsing, transcript tone/delta, signal
clamping + aggregation, 8-K novelty, Firecrawl-first ingest (1 sec-api call
asserted), budget-guard block, and the ablation proving NLP moves conviction.

**Phase 2 DoD status:** filing diff produces a scored, passage-cited change
object via the free-of-sec-api Firecrawl path ✓; Firecrawl yields a
transcript-derived `call_tone` signal with cited passages ✓; every NLP output
is a typed signal with `evidence_ids` consumed deterministically (conviction
tilt) ✓; `nlp_audit` ablation proves signals move conviction and coverage % is
reported per memo ✓. Not yet exercised live (awaiting the user's end-to-end
run); revision-momentum (Finnhub estimates) left to the Phase 3 backlog.

## Phase 3 — Quant Rigor (complete; pure math, fully offline-tested)

Built in the mandated order 3.1 → 3.5. Almost entirely deterministic math
with no LLM/API, so every piece is unit-tested without live calls.

- **3.1 anti-overfitting** (`quant/overfitting.py`): `HypothesisLedger`
  (records every trial — the denominator the stats need); **Probabilistic +
  Deflated Sharpe** (Bailey & López de Prado — corrects Sharpe for trial count
  and skew/kurtosis); **PBO via CSCV** (Bailey et al.); **purged + embargoed
  k-fold** splits (López de Prado) preventing leakage; bootstrap Sharpe CI.
  Verified: noise → DSR 0 / PBO 0.66 (overfit); genuine signal → PBO 0
  (robust); more trials lowers DSR.
- **3.2 portfolio** (`quant/portfolio.py`): native **Hierarchical Risk
  Parity** (scipy clustering — no cvxpy/PyPortfolioOpt dependency) on the
  existing Ledoit-Wolf-shrunk covariance; `ideas_to_views` maps each idea's
  implied move + conviction → Black-Litterman view + omega; `construct_portfolio`
  returns weights **with per-idea view→weight receipts** (the §3.2
  traceability), BL with graceful HRP fallback.
- **3.3 honest simulator** (`quant/track_record.py`, `infra/track_record_store.py`):
  costs/slippage/look-ahead already lived in `backtester.py`; added a
  **tamper-evident hash chain** over scored signals (detects edit / reorder /
  deletion vs a stored anchor) with `track_record_anchors` table +
  `GET /api/track-record/verify` and `POST /api/track-record/anchor`; and wired
  the **point-in-time guard** into the live scorer (`agents/scorer.py` now only
  prices bars dated on/after the signal date — a look-ahead can't inflate the
  record).
- **3.4 conviction calibration** (`quant/conviction.py`): `compose_conviction`
  turns named sub-scores (factor, filing_change, call_tone, revision_momentum,
  options_positioning, regime_fit) with **explicit weights** into a conviction
  magnitude + direction, **each sub-score a receipt** (no LLM mood score);
  `brier_score`, `reliability_curve`, `calibration_report` (vs the live scored
  track record), and `suggest_reweight` (re-weight by realized edge).
- **3.5 regime-conditional factor tilting** (`quant/regime_factors.py`):
  blends per-regime factor profiles by the HMM posterior
  (`risk_on/late_cycle/transition/risk_off`) → tilted value/momentum/quality/
  low_vol/size weights + receipts; `regime_fit_score` feeds conviction's
  `regime_fit` sub-score (momentum fits risk_on +, misfits risk_off −).
- **DoD wiring**: `backtester.py` now augments every report with
  `augment_backtest_overfitting` — the headline is the **deflated** Sharpe
  (raw Sharpe is no longer the headline), with a bootstrap CI and a PBO note
  (PBO needs multiple configs).

**Tests:** `backend/tests/test_quant_rigor.py` (18 tests). Full suite now
**44/44 green**, no live calls.

**Phase 3 DoD status:** no backtest headlines raw Sharpe (deflated Sharpe +
bootstrap CI shown; PBO when multi-config) ✓; weights come from BL/HRP on
shrunk covariance with per-idea view→weight receipts ✓; simulator enforces
the point-in-time guard and the track record is tamper-evident ✓; conviction
is a decomposable receipted composite with a calibration (reliability + Brier)
report against the live track record ✓. Calibration *panel* (frontend) and
wiring the composite into the live Strategist conviction are follow-ups for
the end-to-end run; 3.6 extras (options-implied signals, PEAD via Finnhub,
cross-sectional GBM, coverage-driven confidence downgrade) remain backlog.
