# REPO_MAP.md — Phase 0 Orientation

> Produced per the Build Plan's Phase 0 gate. Answers the five orientation
> questions, inventories what already exists vs. what each phase must build,
> and proposes a Phase 1 implementation approach. **No phase code written yet.**

Repo root: `c:\Users\wfeva\Projects\alphaengine` · Backend: Python (FastAPI +
LangChain/LangGraph) · Frontend: Next.js 16 / TS · DB: Postgres (Railway) /
SQLite local.

---

## 1. Where data fetching lives & how it's cached

**One module per source** under `backend/data/`:

| Client | Source | Notes |
|--------|--------|-------|
| `fred_client.py` | FRED macro | Circuit breaker (5 fails → 60s open), 3-worker concurrency cap |
| `market_client.py` | Yahoo Finance | prices / fundamentals / options / total-return |
| `news_client.py` | NewsAPI + Finnhub | Finnhub uses free `company-news` (not premium sentiment) |
| `alpha_vantage_client.py` | Alpha Vantage | quota detected reactively from response body |
| `sec_client.py` | **sec-api.io only** | no direct `data.sec.gov`, **no User-Agent** |
| `firecrawl_client.py` | Firecrawl | `scrape_url()` + `search_web()`; validation layer, not transcripts |

**Caching** (`backend/infra/cache.py`): in-memory `OrderedDict` TTL cache with
LRU eviction, mutex-protected. **String keys, not content hashes. No DB
persistence — process restart flushes everything.** HTTP retry/backoff/jitter
+ 429 `Retry-After` handling in `infra/http.py`.

TTLs: FRED 6h/3h · market prices 15m, fundamentals 1h, options 15m · NewsAPI
30m · Finnhub 15m · Alpha Vantage 4h · Firecrawl 30m · **SEC: none**.

**Rate limiting / budget guards:** none proactive. FRED circuit breaker and
Alpha Vantage reactive quota-detection are the only guards. No per-source rate
limiter, no daily budget guard.

> **Gap for Phase 1 (evidence store) & Cost Discipline:** caching is
> in-memory + string-keyed. The plan wants a content-hash-keyed, DB-persisted
> evidence store that doubles as the fetch cache. This is net-new.

---

## 2. Memo pipeline & the compute / LLM boundary

Entry point: `agents/orchestrator.py :: run_research_desk(query, user_id,
parent_memo_id)`. LangGraph sequential `StateGraph`:

```
interpreter → research → risk → strategy → synthesizer → END
```

- Agents: `query_interpreter` and `cio_synthesizer` are **pure-reasoning**
  (direct `.ainvoke`); `research_analyst`, `risk_manager`,
  `portfolio_strategist` are **tool-calling** (`BaseAgent` + `AgentExecutor`).
- **The compute/LLM boundary is currently blurred:** each tool-calling agent
  *both* fetches data (via tools) *and* narrates in the same LLM loop. There is
  no separate "compute → Fact Sheet → narrate" split.
- **Existing provenance is post-hoc**, in `run_synthesizer`:
  - `infra/lineage.py` extracts `{type,id,url,...}` sources from each agent's
    `intermediate_steps` (tool-call tuples).
  - `infra/citations_resolver.py` resolves agent-emitted `[[src:type:id]]`
    markers → numbered `[N]` index, auto-backfills uncited ideas, drops
    hallucinated citations.
  - `infra/coverage.py` grades `verified | partial | unverified`.
  - `base_agent._ground_check()` is a numeric-tripwire (flags numbers in prose
    absent from tool outputs) — **soft signal, not a hard gate**.

> **Phase 1 turns this soft, post-hoc system into a hard gate** with a real
> evidence store and a validator that *rejects* a memo containing an
> uncited number. The seams (`lineage`, `citations_resolver`, `coverage`,
> `_ground_check`) are exactly where this work lands — extend, don't replace.

---

## 3. Quant metrics — location & language

All Python, `backend/quant/`. Pure math, no LLM coupling.

**Exists:** `risk.py` (Ledoit-Wolf shrinkage, VaR/CVaR, bootstrap),
`performance.py` (Sharpe/Sortino/Calmar/drawdown/alpha/beta), `regime.py`
(4-state Gaussian HMM + hysteresis + `regime_size_multiplier` +
`regime_conditional_returns`), `optimizer.py` (**custom** mean-variance +
Black-Litterman + ridge — *not* PyPortfolioOpt), `signal_validation.py` (IC,
ICIR, hit-rate-by-conviction, alpha decay), `backtester.py` (walk-forward with
slippage/transaction-cost/capacity + **look-ahead guard at `backtester.py:133-141`**),
`factors.py` (OLS factor loadings, VIF, FF5-style ETF proxies),
`options_analytics.py`, `curve.py`, `stress.py`, `pairs.py`, `limits.py`.

**Absent (Phase 3 builds these):** Deflated Sharpe, PBO, CSCV, purged/embargoed
CV, hypothesis ledger; HRP; tamper-evident track record; Brier score /
reliability curves; regime→*factor-weight* tilting (today regime only tilts
position size). Conviction is analyst-emitted (LLM), **not** a decomposable
deterministic composite.

**Deps (`requirements.txt`):** `hmmlearn`, `scipy`, `statsmodels`,
`scikit-learn` present. **`PyPortfolioOpt` NOT installed** (Phase 3.2 needs it).

---

## 4. Postgres schema (`backend/db/models.py`)

Memo/idea/position/track-record tables exist; **no provenance tables.**

- Memo/threads: `intelligence_memos` (already has `lineage`, `citation_index`,
  `coverage`, `verification_status` JSON columns), `morning_reports`.
- Ideas/positions: `trades`, `portfolio`, `portfolio_snapshots`,
  `position_snapshots`, `signal_scores` (1d/5d/20d forward returns + hit flags).
- Quant/scan: `backtest_runs`, `backtest_results`, `factor_exposures`,
  `regime_states`, `macro_snapshots`, `scan_findings`, `scan_runs`, `watchlist`.
- User: `user_profiles`, `user_risk_profiles`.

> **Phase 1 net-new:** `evidence` (computed + source receipts, content-hash
> keyed) and `claim_evidence` join. **No table persists fetched raw data
> today** — the evidence store is the first place that happens.

---

## 5. How LLM calls are made

`agents/base_agent.py :: get_llm()` — single shared `ChatAnthropic`,
**`claude-sonnet-4-20250514`**, `temperature=0`, `max_tokens=4096`,
`max_retries=4`, `timeout=90`. Every agent (tool-calling and pure-reasoning)
uses this one model.

- **No model tiering** (no Haiku for bulk extraction / Opus for synthesis).
- **No prompt caching** (`langchain-anthropic==0.3.9`; no `cache_control`).
- **No Batch API.**
- Streaming = SSE **tool-activity feed** via `stream_callbacks.DeskStreamCallback`
  (LangChain callbacks), not token streaming.
- Config (`config.py`) exposes only `ANTHROPIC_API_KEY` — no model config.

> **Cost Discipline (cross-cutting):** all three Anthropic levers are unused.
> The bulk NLP load Phase 2 adds (filing diffs, transcript scoring) is exactly
> the workload that should route through Batch + prompt caching + Haiku. An
> `llm/client.py` tiering/caching layer is the right home.

---

## Phase 1 implementation approach (proposed — for confirmation)

Reuse the existing provenance plumbing rather than rebuild it. Concretely:
(1) Add `evidence` + `claim_evidence` tables and a `backend/provenance/` store
that upserts by `content_hash` — wire it underneath the existing data clients
so every FRED/Yahoo/SEC/etc. fetch writes a **source/computed receipt** (this
also gives us the persistent, content-hash cache the Cost Discipline section
wants — one mechanism, two wins). (2) Restructure `orchestrator` memo
generation into the three explicit stages the plan names: a **compute** stage
that runs all math + retrieval and emits a Fact Sheet of `evidence` rows (IDs +
values + passages), a **narrate** stage that prompts the LLM with *only* the
Fact Sheet and forces inline `[[ev:ID]]` markers, and a **validate** stage that
hardens today's soft `_ground_check`/coverage into a real linter that
**hard-fails** any memo with an orphan numeric token (auto-repair re-prompt,
then refuse). (3) Extend the `Citation` model + `citations_resolver` to target
`evidence.id` receipts, and surface clickable receipts in UI + the PDF
appendix. The hallucination-injection regression test (plan §1.5 / Verification)
is the acceptance gate. Smallest-change bias: extend `lineage`,
`citations_resolver`, `coverage`, and `_ground_check` in place; leave
`// TODO(alpha):` notes where Phase 2/3 will hook in.
