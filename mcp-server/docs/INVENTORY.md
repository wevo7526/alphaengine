# T0 — Backend inventory (seam scope, contract ground truth)

> The pre-build audit required by MASTER_PLAN §8 / build-spec T0. Locks the
> scope of the data-injection seam, the envelope's ground-truth fields, the
> streaming mechanism the agent-job surface reuses, and the Decision Gate
> signature. Written from a read of orchestrator.py, schemas.py,
> desk5_decision_gate.py, main.py, and every backend/data + backend/quant
> module. Done = this file committed.

---

## 1. Data-fetch egress points (what the seam must cover)

Every external network call funnels through nine client surfaces in
`backend/data/`. The seam (T5) must intercept all of them so that in
data-provided mode, **none** fire.

| Client | Egress methods (network) | Cache |
|---|---|---|
| `sec_client.SECDataClient` | `get_recent_filings`, `get_filings_by_date_range`, `search_filings_fulltext`, `extract_mda`, `extract_risk_factors`, `extract_financial_statements`, `extract_business_description`, `get_insider_trades`, `get_13f_holdings`, `search_13f_for_ticker` (+ `a*` async variants) | sec-api SDK |
| `fred_client.FREDDataClient` | `get_macro_snapshot`, `get_series_history`, `get_single_indicator`, `get_risk_free_rate` (+ `a*`) | 1–6h TTL + circuit breaker |
| `market_client.MarketDataClient` | `get_price_history`, `get_total_return_history`, `get_fundamentals`, `get_earnings_calendar`, `get_consensus`, `get_options_chain` (+ `a*`) | 15m–1h TTL |
| `news_client.NewsDataClient` | `get_ticker_news`, `get_market_sentiment_finnhub`, `get_market_news_finnhub` (+ `a*`) | 15–30m TTL |
| `alpha_vantage_client.AlphaVantageClient` | `get_top_movers`, `get_rsi`, `get_macd`, `get_bollinger_bands`, `get_sma`, `get_ema` (+ `a*`) | 4h TTL |
| `firecrawl_client` (module fns) | `scrape_url`, `search_web`, `scrape_full` (+ `a*`) | 30m / 6h TTL |
| `market_screener` | `screen_market`, `screen_market_tickers` (calls yfinance `screen()` + AlphaVantage internally) | 1h TTL |
| `smart_money` | none — in-memory seed list | — |
| `events` | none — hardcoded calendar | — |

### Call-sites that invoke those clients (the injection points)

Instantiation is **scattered** — module-level singletons per agent/quant
module, plus a few function-scoped instances. There is no single factory, so
the seam intercepts at the **client method layer** (a request-scoped
`contextvars` context each method consults before any network call), not at
construction.

- **Agents** (`backend/agents/`): `research_analyst.py` (FRED, Market, News, SEC, AlphaVantage — ~20 tool wrappers + `search_web` + `screen_market`), `risk_manager.py` (FRED, Market), `query_interpreter.py` (Market + `screen_market_tickers`), `portfolio_strategist.py` (Market), `desk3_position_risk.py` (Market), `scorer.py` (Market), `nlp/filing_ingest.py` + `nlp/transcripts.py` (SEC + firecrawl).
- **Orchestrator** (`orchestrator.py`): `_fetch_macro_context` (FRED), `_fetch_live_prices_for` (Market.get_fundamentals), `_fetch_portfolio_snapshot` (Market) — plus DB reads (memos, trades, scorecard) that are **not** market-data egress.
- **Quant** (`backend/quant/`): `computations.py`, `backtester.py`, `backtesting.py`, `curve.py`, `factors.py`, `pairs.py`, `performance.py`, `stress.py`, `options_analytics.py`, `optimizer.py` — each either holds a module-level `MarketDataClient`/`FREDDataClient` or instantiates one inline.
- **Infra**: `eod_snapshot.py` (Market) — not on the request path.
- **Entry**: `main.py` instantiates `fred_client`, `market_client`, `news_client`, `sec_client` as module singletons.

**Seam conclusion:** intercept at the data-client method boundary via a
request context. In provided-mode, methods read supplied data or raise a
`FetchForbidden` guard error; a test asserts no socket opens. The
`quant_core/` extraction (T1) sidesteps this entirely for the deterministic
plane — those functions take arrays directly and import no data layer.

---

## 2. SignalEnvelope ground truth — `IntelligenceMemo` / `TradeIdea`

`agents/schemas.py`. The envelope (T3) is a projection of these; see
`SIGNAL_ENVELOPE.md` for the field-by-field mapping.

- **`TradeIdea`**: `ticker`, `direction` (SignalDirection enum, long/short aliases), `conviction` (0–100), `thesis`, `entry_zone`, `stop_loss`, `take_profit`, `risk_reward_ratio`, `position_size_pct`, `time_horizon`, `catalysts`, `risks`, `beta_to_spy`, `sector`, `regime_conditional_size_pct`, `structure_type` (outright/pair/spread/calls/puts/hedge), `pair_short_leg`, `style_label`, `market_cap_bucket`, `alpha_share`/`factor_share`/`idiosyncratic_sharpe`, `tier`, `screen_source`, `citations: list[Citation]`.
- **`IntelligenceMemo`**: `query`, `timestamp`, `title`, `executive_summary`, `analysis`, `key_findings`, `macro_regime`, `overall_risk_level`, `risk_factors: list[RiskFactor]`, `trade_ideas: list[TradeIdea]`, `decision`/`decision_reason`/`decision_confidence` (Decision Gate), `lineage` (provenance sources), `citation_index: list[Citation]`, `coverage`, `verification_status`, `falsification_criteria`, `mandate_warnings`, `regime_sensitivity`, `macro_context`, `evidence_receipts`/`evidence_links` (exclude=True).
- **`Citation`** (`agents/citations.py`): `{source_type, source_id, url?, label?, excerpt?, n}` → maps to envelope `provenance[]`.

---

## 3. Streaming mechanism (reused by the agent-job surface, T7)

- Entry point: `agents/orchestrator.run_research_desk(query, user_id=None, parent_memo_id=None) -> IntelligenceMemo`. A compiled LangGraph `StateGraph`: `interpreter → research → risk → strategy → synthesizer → END`, run via `graph.ainvoke(initial_state)`.
- Per-agent timeouts via `_with_timeout`: interpreter 45s, research 180s, risk 90s, strategy 90s, CIO 120s. **A full slate is tens of seconds to minutes** → must be an async job, never a sync request.
- Streaming today: `agents/stream_callbacks.py` + the SSE endpoint in `main.py` (token/phase events over `text/event-stream`). The job surface (T7) reuses this transport: submit → `job_id` → stream the same SSE → terminal `SignalEnvelope`.
- Agent singletons live at orchestrator import; data-client caches persist across requests.

---

## 4. Decision Gate signature (reused for `risk.gate`, T3)

`agents/desk5_decision_gate.compute_decision(...)` — **pure, no LLM, no I/O.**

```python
compute_decision(
    trade_ideas: list[dict],
    macro_regime: str,
    overall_risk_level: str,
    min_conviction_go: int = 75,
    min_conviction_watch: int = 50,
    scorecard: dict | None = None,
) -> dict   # {decision: GO|WATCH|NO-GO, reason, confidence(0-100),
            #  top_conviction, regime_aligned, regime, risk_level,
            #  track_record_adjustment}
```

Envelope mapping: **GO → `gate: "pass"`, WATCH → `"warn"`, NO-GO → `"block"`.**
Reuse verbatim; do not reimplement.

---

## 5. Pinned numeric stack (frozen for determinism, T1)

From the backend venv (`backend/.venv`), the versions the golden fixtures encode:

```
python 3.10 · numpy 2.2.6 · scipy 1.15.3 · statsmodels 0.14.6
scikit-learn 1.7.2 · pandas 2.3.3 · hmmlearn 0.3.3
```

A minor bump in any of these can move a regression tail → a different signal,
so `mcp-server/requirements.txt` pins them `==` and CI runs the golden tests.
