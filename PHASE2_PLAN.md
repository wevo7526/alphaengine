# ALPHA ENGINE — Phase 2 Build Plan

## Objective

Transform Alpha Engine from a 5-agent linear pipeline into a 6-desk / 12-agent hedge fund simulation with rich real-time tracing, auto-populating findings, enforced risk gates, and a closed-loop feedback system.

**Guiding principle:** Ship incrementally. Every step produces a working system. No big-bang rewrites.

---

## Priority Order

```
P1  Rich Desk Tracing          ← Makes the existing pipeline visible and impressive
P2  Auto-Populating Findings   ← System finds alpha without user input
P3  Portfolio P&L + Positions  ← Track whether signals make money
P4  Agent Split (5→12)         ← Desk architecture migration
P5  Enforced Risk Gates        ← Risk desk gets kill authority
P6  Decision Gate (GO/NO-GO)   ← CIO sign-off with hard thresholds
P7  Signal Scorecard           ← Feedback loop — score every past signal
P8  P&L Attribution            ← Decompose returns by desk and factor
```

---

## P1: Rich Desk Tracing

**Goal:** Replace the 5-dot spinner with a live activity feed showing tool calls, data summaries, agent reasoning, risk decisions, and timing per desk.

### P1.1 — Backend: Stream Callback Handler

**New file:** `backend/agents/stream_callbacks.py`

Create `DeskStreamCallback(AsyncCallbackHandler)`:
- Constructor takes an `asyncio.Queue` and a `desk_name` string
- `on_tool_start(tool_name, tool_input)` → pushes `{type: "tool_call", desk, tool, args_summary}` to queue
  - `args_summary`: extract ticker or key arg, max 80 chars (e.g., `"ticker=NVDA"`)
- `on_tool_end(output)` → pushes `{type: "tool_result", desk, tool, result_summary}` to queue
  - `result_summary`: smart summarizer per tool type:
    - `get_fundamentals` → `"P/E 40.3x, Rev +73%, Margin 55.8%"`
    - `get_macro_snapshot` → `"13/13 indicators, VIX 18.36, Fed Funds 3.64%"`
    - `get_ticker_news` → `"5 articles, top: 'NVDA beats earnings expectations'"`
    - `get_options_chain` → `"P/C 0.48, IV 38%, implied move 3.2%"`
    - Default: first 100 chars of str(output)
- `on_tool_error(error)` → pushes `{type: "tool_error", desk, tool, error: str}`
- `on_agent_action(action)` → pushes `{type: "agent_action", desk, action_summary}`
- No `on_llm_new_token` — don't stream raw LLM tokens (too noisy, burns context)

**Summarizer functions** live in the same file. One function per tool name that extracts the key numbers from the result dict. Fallback: `str(result)[:100]`.

**Files changed:**
- New: `backend/agents/stream_callbacks.py`

### P1.2 — Backend: Wire Callbacks Into Agents

**Modified:** `backend/agents/base_agent.py`
- `analyze(context, callbacks=None)` — accept optional `callbacks` list
- Pass `callbacks` to `executor.ainvoke({"input": prompt}, config={"callbacks": callbacks})`

**Modified:** `backend/agents/query_interpreter.py`
- `interpret(query, callbacks=None)` — pass callbacks to `llm.ainvoke(..., config={"callbacks": callbacks})`

**Modified:** `backend/agents/cio_synthesizer.py`
- `synthesize(context, callbacks=None)` — same pattern

### P1.3 — Backend: Streaming Endpoint Upgrade

**Modified:** `backend/main.py` — `/api/analyze/stream`

Current flow:
```python
yield send({"phase": "researching"})
output = await _with_timeout(_research_analyst.analyze({"plan": plan_data}), ...)
yield send({"phase": "researching_done"})
```

New flow:
```python
import asyncio

queue = asyncio.Queue()

# Create per-desk callbacks
research_cb = DeskStreamCallback(queue, desk="research")

# Start agent in background task
async def run_agent():
    return await _research_analyst.analyze({"plan": plan_data}, callbacks=[research_cb])

task = asyncio.create_task(run_agent())

# Drain queue while agent runs, yielding SSE events
while not task.done():
    try:
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        yield send(event)
    except asyncio.TimeoutError:
        yield keepalive()

# Get final result
output = await task
yield send({"type": "desk_done", "desk": "research", "summary": "4 tickers, 8 tools"})
```

This pattern repeats for each desk. The key insight: the agent runs in a background task while we drain the event queue and yield SSE events. The user sees tool calls in real time.

**New SSE event types** (backward compatible — old events still sent):

| type | payload | when |
|---|---|---|
| `desk_start` | `{desk, label, agents[]}` | Desk begins |
| `tool_call` | `{desk, tool, args_summary}` | Agent calls a tool |
| `tool_result` | `{desk, tool, result_summary}` | Tool returns |
| `tool_error` | `{desk, tool, error}` | Tool fails |
| `agent_thinking` | `{desk, text}` | Agent reasoning snippet (optional) |
| `desk_done` | `{desk, summary, duration_ms}` | Desk completes |
| `risk_gate` | `{ticker, approved, adjusted_size, reasons[]}` | Risk decision |
| `decision` | `{decision, reason, confidence}` | CIO go/no-go |

Old events (`phase`, `complete`, `error`) continue to fire at the same points for backward compatibility. The frontend can use either old or new events.

### P1.4 — Frontend: Parse New Events

**Modified:** `frontend/hooks/useAnalysis.ts`

Add new fields to `AnalysisRun`:
```typescript
interface DeskActivity {
  type: "tool_call" | "tool_result" | "tool_error" | "agent_thinking" | "risk_gate" | "decision";
  desk: string;
  tool?: string;
  args_summary?: string;
  result_summary?: string;
  text?: string;
  error?: string;
  approved?: boolean;
  reasons?: string[];
  timestamp: number;
}

interface DeskState {
  desk: string;
  label: string;
  status: "pending" | "active" | "done";
  activities: DeskActivity[];
  duration_ms?: number;
  summary?: string;
}

// Add to AnalysisRun:
desks: DeskState[];
```

SSE parser adds a new branch: if event has `type` field (new format), push to the appropriate desk's activity array. Old `phase` events still update the phase field for backward compat.

### P1.5 — Frontend: Rebuild AnalysisTrace

**Rebuilt:** `frontend/components/AnalysisTrace.tsx`

New structure:
```
<AnalysisTrace>
  {desks.map(desk => (
    <DeskSection 
      key={desk.desk}
      desk={desk}
      expanded={desk.status === "active" || expandedDesk === desk.desk}
      onToggle={() => toggleDesk(desk.desk)}
    >
      {desk.activities.map(activity => (
        <ActivityItem key={activity.timestamp} activity={activity} />
      ))}
    </DeskSection>
  ))}
</AnalysisTrace>
```

**DeskSection** component:
- Header: desk name, status dot (green/blue/gray), duration, collapse/expand chevron
- When collapsed: one-line summary (e.g., "4 tickers researched, 8 tool calls · 68s")
- When expanded: full activity feed
- Active desk auto-expanded with pulsing border

**ActivityItem** component renders based on `type`:
- `tool_call`: lightning bolt icon + tool name + args in mono font. Dim color.
- `tool_result`: same line updates with result summary. Brighter color.
- `tool_error`: red text with error message.
- `agent_thinking`: speech bubble icon + italic text, truncated to 200 chars with expand.
- `risk_gate`: shield icon + APPROVED (green) or BLOCKED (red) + reasons.
- `decision`: GO (green badge) / NO-GO (red) / WATCH (yellow).

**Animation:** New activities slide in from top with a subtle fade. Active desk has a pulsing left border accent.

### P1 Deliverable

User runs analysis → sees each desk activate in sequence → watches tool calls appear in real time ("Fetching NVDA fundamentals... P/E 40.3x") → sees risk gate decisions → sees GO/NO-GO → memo renders below.

**Estimated scope:** ~200 lines backend (callback + wiring), ~300 lines frontend (trace rebuild + hook changes). No DB changes. No API shape changes.

---

## P2: Auto-Populating Findings

**Goal:** When the user opens the app, the system has already found opportunities overnight. No manual trigger needed.

### P2.1 — Backend: Scanner DB Models

**Modified:** `backend/db/models.py`

```python
class ScanFindingRecord(Base):
    __tablename__ = "scan_findings"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    ticker = Column(String(10), nullable=False)
    finding_type = Column(String(30), nullable=False)
    # Types: insider_cluster, earnings_surprise, momentum_break, rsi_extreme,
    #        volume_spike, sentiment_shift, macro_shift, filing_alert
    priority = Column(String(10), nullable=False)  # high, medium, low
    headline = Column(String(200), nullable=False)
    detail = Column(Text)
    data_json = Column(JSON)  # Raw anomaly data for drill-down
    created_at = Column(DateTime, server_default=func.now())

class ScanRunRecord(Base):
    __tablename__ = "scan_runs"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    universe_size = Column(Integer)
    findings_count = Column(Integer)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    status = Column(String(20), default="running")  # running, completed, failed
```

### P2.2 — Backend: Scanner Logic

**New file:** `backend/agents/scanner.py`

Pure computation — no LLM calls. Fast (30-60s for 50 tickers).

```python
async def run_scan(tickers: list[str], user_id: str = None) -> list[dict]:
    """Scan universe for anomalies. Returns list of findings."""
```

**Anomaly checks per ticker** (all use existing data clients + quant modules):

| Check | Data Source | Flag Condition |
|---|---|---|
| RSI extreme | `market_client.get_price_history()` → compute RSI locally | RSI < 30 or > 70 |
| Volume spike | `market_client.get_price_history()` | Today volume > 2x 20-day avg |
| MA breakout | `market_client.get_price_history()` | Price crossed 200-day MA in last 2 days |
| Insider cluster | `sec_client.get_insider_trades()` | 3+ insider buys within 30 days |
| Sentiment shift | `news_client.get_ticker_news()` + `nlp/sentiment.score_articles()` | Compound score delta > 0.3 vs prior |
| Earnings surprise | `market_client.get_fundamentals()` | Large 1-day price move + recent 8-K |

**Macro shift checks** (run once per scan, not per ticker):

| Check | Data Source | Flag Condition |
|---|---|---|
| VIX spike | `fred_client.get_macro_snapshot()` | VIX change > 3 points |
| Credit widening | `fred_client.get_macro_snapshot()` | Credit spread change > 20bp |
| Yield curve shift | `fred_client.get_macro_snapshot()` | T10Y2Y change > 10bp |

**Concurrency:** Use `ThreadPoolExecutor(max_workers=4)` for per-ticker checks (existing pattern from FRED parallel fetch).

**API budget:** Each ticker needs ~2-3 API calls (fundamentals + price + news). For 50 tickers = ~150 calls. NewsAPI (100/day) is the bottleneck — skip news for low-priority tickers. Prioritize: watchlist tickers first, then sector ETFs, then broad universe.

### P2.3 — Backend: Scanner Endpoints

**Modified:** `backend/main.py`

```python
GET  /api/scan/latest          # Most recent findings from DB (instant)
POST /api/scan/trigger          # Trigger scan in background, return immediately
GET  /api/scan/status           # Is a scan currently running?
```

`POST /api/scan/trigger` runs the scanner in a background `asyncio.Task`. Stores findings to DB as they're found. Returns `{scan_id, status: "started"}`.

`GET /api/scan/latest` returns findings from the last completed scan, grouped by priority.

### P2.4 — Backend: Default Universe

**New file:** `backend/agents/universe.py`

Defines the default scan universe:
```python
SECTOR_ETFS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "XLF", "XLK", "XLE", "XLV", "XLI"]
MEGA_CAPS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B"]
# + user's watchlist tickers from DB
# + tickers from open trades
```

Total default universe: ~30-50 tickers. Expandable via watchlist.

### P2.5 — Backend: Watchlist CRUD

**Modified:** `backend/db/models.py`

```python
class WatchlistRecord(Base):
    __tablename__ = "watchlist"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    ticker = Column(String(10), nullable=False)
    notes = Column(Text)
    added_at = Column(DateTime, server_default=func.now())
```

**Modified:** `backend/main.py`

```python
GET    /api/watchlist              # List user's watchlist
POST   /api/watchlist              # Add ticker(s): {tickers: ["AMZN", "CRM"]}
DELETE /api/watchlist/{ticker}     # Remove ticker
```

### P2.6 — Frontend: Scan Findings Component

**New component:** `frontend/components/ScanFindings.tsx`

Renders findings grouped by priority (HIGH → MEDIUM → LOW):
- Each finding: ticker badge, finding type icon, headline, detail text, "Analyze →" button
- "Analyze →" navigates to `/analysis?q=Deep+analysis+of+{ticker}+—+{headline}`
- Stale indicator: "Last scan: 6:32 AM ET" with manual refresh button
- Loading state while scan runs

**Modified:** `frontend/app/page.tsx` (Home)

Insert `<ScanFindings />` above the macro dashboard. On mount:
1. Fetch `GET /api/scan/latest`
2. If no findings or findings older than 6 hours: auto-trigger `POST /api/scan/trigger`
3. Poll `GET /api/scan/status` every 30s while scan running
4. Refetch findings when scan completes

**Modified:** `frontend/lib/api.ts`

Add: `scanLatest()`, `scanTrigger()`, `scanStatus()`, `watchlist()`, `addToWatchlist(tickers)`, `removeFromWatchlist(ticker)`

### P2.7 — Frontend: Analysis Auto-Submit

**Modified:** `frontend/app/analysis/page.tsx`

Read `?q=` query param on mount. If present:
- Pre-fill the input field
- Auto-submit the analysis
- Clear the query param from URL

This makes the "Analyze →" links from scan findings seamless — one click from finding to running analysis.

### P2 Deliverable

User opens app → sees "Overnight Scan" section with flagged tickers → clicks "Analyze →" on AMZN insider cluster → jumps to Analysis page → analysis auto-starts → rich trace shows desks working.

**Estimated scope:** ~150 lines scanner logic, ~80 lines endpoints, ~50 lines models, ~200 lines frontend. 2 new DB tables, 6 new endpoints.

---

## P3: Portfolio P&L + Positions

**Goal:** Aggregate open trades into live positions with real-time P&L. The user needs to know if their book is making money.

### P3.1 — Backend: Positions Endpoint

**Modified:** `backend/main.py`

```python
GET /api/portfolio/positions    # Aggregated positions with live prices + P&L
```

Logic:
1. Query all open `TradeRecord` for current user
2. Group by ticker, compute: total shares, avg entry price, total cost basis
3. Fetch current prices concurrently (`ThreadPoolExecutor`)
4. Compute per-position: unrealized P&L ($ and %), weight in portfolio
5. Compute portfolio summary: total value, total cost, total unrealized P&L, daily P&L estimate, realized P&L (from closed trades)
6. Return everything in one response

No new DB models — computed on-the-fly from `TradeRecord` + live market data.

### P3.2 — Frontend: Positions Tab

**Modified:** `frontend/app/portfolio/page.tsx`

New tab "Positions" (becomes the default tab, before Journal):

**Summary cards row:**
- Total Value (portfolio_value)
- Unrealized P&L (green/red with %)
- Realized P&L (from closed trades)
- Win Rate (closed trades with positive P&L / total closed)

**Positions table:**
| Ticker | Direction | Avg Entry | Current | P&L % | P&L $ | Weight | Stop | Target |
|--------|-----------|-----------|---------|-------|-------|--------|------|--------|
| NVDA   | LONG      | $195.00   | $197.50 | +1.28%| +$320 | 3.75%  | $180 | $220   |

Color-coded P&L. Clicking a row could expand to show the underlying trades.

### P3 Deliverable

Portfolio page opens to Positions tab → 4 summary cards → live positions table with current prices and P&L.

**Estimated scope:** ~80 lines backend endpoint, ~120 lines frontend tab. No DB changes.

---

## P4: Agent Split (5 → 12)

**Goal:** Refactor existing 5 agents into 12 agents across 6 desks. Same outputs, cleaner separation of concerns.

### P4.1 — Split Research Analyst

**Current:** `research_analyst.py` — 1 agent with 18 tools that gathers data AND synthesizes thesis

**After:**
- `backend/agents/desk2_data_analyst.py` — Inherits from BaseAgent, keeps all 18 tools, focuses on data gathering only. Output: raw `ResearchData` (facts, no narrative).
- `backend/agents/desk2_thesis_builder.py` — Pure LLM reasoning (no tools). Takes `ResearchData` as input, produces investment thesis with bull/bear/base cases.

### P4.2 — Split Risk Manager

**Current:** `risk_manager.py` — 1 agent that classifies regime AND assesses position risk

**After:**
- `backend/agents/desk3_macro_regime.py` — Uses FRED tools. Output: regime classification + confidence + risk narrative.
- `backend/agents/desk3_position_risk.py` — Calls `quant/risk.py` functions programmatically (not via LLM). Returns hard risk gate result: `{approved, adjusted_size, reasons[]}`.

The Position Risk Manager is mostly **computation, not LLM reasoning** — it calls `pre_trade_risk_check()`, `compute_marginal_var()`, `check_sector_limits()`, `drawdown_circuit_breaker()` and assembles the result.

### P4.3 — Split Portfolio Strategist

**Current:** `portfolio_strategist.py` — 1 agent that builds trade ideas AND designs hedges

**After:**
- `backend/agents/desk4_trade_structurer.py` — Uses price tools + `quant/optimizer.py`. Output: trade ideas with B-L optimized sizing.
- `backend/agents/desk4_hedge_architect.py` — Uses `quant/options_analytics.py` + `quant/factors.py`. Output: hedging recommendations with specific instruments.

### P4.4 — Split CIO Synthesizer

**Current:** `cio_synthesizer.py` — 1 agent that writes memo

**After:**
- `backend/agents/desk5_memo_writer.py` — Pure LLM. Writes the intelligence memo. Same prompt as current CIO.
- `backend/agents/desk5_decision_gate.py` — Mostly programmatic. Checks: conviction >= 75? Risk gate approved? Regime aligned? Output: `{decision: "GO" | "NO-GO" | "WATCH", reason}`.

### P4.5 — Update Orchestrator

**Modified:** `backend/agents/orchestrator.py`

Update the LangGraph pipeline to chain desks:
```
Desk 1 (if triggered by scan) → Desk 2A → Desk 2B → Desk 3A → Desk 3B → Desk 4A → Desk 4B → Desk 5A → Desk 5B
```

Each desk pair runs sequentially (A then B). The state accumulates as it flows through.

**Modified:** `backend/main.py` — streaming endpoint updated to emit events per desk (already handled by P1 callback architecture).

### P4 Deliverable

Same API shape, same output format, but internally 12 agents across 6 desks. The trace (from P1) now shows the full desk breakdown.

**Estimated scope:** ~600 lines of agent code (split + clean), ~100 lines orchestrator. Most code is moved, not written new.

---

## P5: Enforced Risk Gates

**Goal:** The risk desk has kill authority. Trades that breach limits are blocked, not warned about.

### P5.1 — Backend: Mandatory Risk Check on Trade Execution

**Modified:** `backend/main.py` — `POST /api/portfolio/trade`

Before persisting the trade:
1. Call `pre_trade_risk_check()` with the proposed trade + current portfolio state
2. If `approved == False`: return `{blocked: true, reasons: [...]}` with HTTP 422
3. If `approved == True` but size was adjusted: persist with adjusted size, include `{size_adjusted: true, original_size, adjusted_size, reasons}`
4. Only persist if approved

### P5.2 — Backend: Circuit Breaker Monitoring

**New function in** `backend/main.py` or `backend/quant/risk.py`:

`get_portfolio_drawdown(user_id)`:
1. Query all closed trades for cumulative realized P&L
2. Query all open trades, fetch current prices, compute unrealized P&L
3. Compute high-water mark and current drawdown from peak
4. Feed into `drawdown_circuit_breaker()`
5. Return circuit breaker status

This runs on every trade attempt and is shown on the Risk page.

### P5.3 — Frontend: Risk Gate Badges

**Modified:** `frontend/components/MemoPanel.tsx`

Each trade idea card shows:
- Green "APPROVED" badge if risk check passed
- Red "BLOCKED" badge with reasons if it would fail
- Yellow "SIZE ADJUSTED" badge if size was reduced

**Modified:** `frontend/app/portfolio/page.tsx`

Trade-taking flow: when user clicks "Take Trade", call risk check first. If blocked, show the reasons in a modal/alert instead of silently failing.

### P5 Deliverable

User tries to take a trade → risk gate runs → if blocked, user sees exactly why ("Sector tech at 28%, adding NVDA would breach 30% limit") → if approved, trade persists with adjusted size.

**Estimated scope:** ~60 lines backend logic, ~80 lines frontend badges + blocking UI. No new models.

---

## P6: Decision Gate (GO / NO-GO)

**Goal:** Every analysis gets a clear GO / NO-GO / WATCH recommendation based on hard thresholds, not just LLM prose.

### P6.1 — Backend: Decision Gate Logic

**New file:** `backend/agents/desk5_decision_gate.py` (or inline in orchestrator)

Programmatic decision based on:
```python
def compute_decision(plan, risk_data, strategy_data, portfolio_state):
    trade_ideas = strategy_data.get("trade_ideas", [])
    top_conviction = max((t.get("conviction", 0) for t in trade_ideas), default=0)
    regime = risk_data.get("macro_regime", "unknown")
    risk_level = risk_data.get("overall_risk_level", "elevated")
    
    # Hard thresholds
    if top_conviction >= 75 and risk_level not in ["high", "extreme"]:
        decision = "GO"
    elif top_conviction >= 50:
        decision = "WATCH"
    else:
        decision = "NO-GO"
    
    # Regime override: CONTRACTION + bullish ideas → downgrade to WATCH
    if regime == "contraction" and decision == "GO":
        decision = "WATCH"
        reason = "Regime CONTRACTION dampens bullish conviction"
    
    return {decision, reason, confidence: top_conviction}
```

### P6.2 — Backend: Include Decision in Memo Output

**Modified:** streaming endpoint and orchestrator

After CIO synthesis, run decision gate. Include `decision` field in the final memo output:
```json
{
  "decision": "GO",
  "decision_reason": "Top conviction 85, risk elevated but regime-aligned",
  "decision_confidence": 85,
  ...existing memo fields
}
```

### P6.3 — Frontend: Decision Badge

**Modified:** `frontend/components/MemoPanel.tsx`

Large badge at top of memo:
- GO: green badge, bold
- NO-GO: red badge with reason
- WATCH: yellow badge with reason

### P6 Deliverable

Every memo has a clear GO/NO-GO/WATCH badge with programmatic reasoning. User knows instantly whether to act.

**Estimated scope:** ~40 lines backend logic, ~30 lines frontend badge. Minimal.

---

## P7: Signal Scorecard

**Goal:** Track every past signal at 1d/5d/20d intervals. Compute hit rate, IC, and average P&L per desk.

### P7.1 — Backend: Score DB Model

**Modified:** `backend/db/models.py`

```python
class SignalScoreRecord(Base):
    __tablename__ = "signal_scores"
    id = Column(String, primary_key=True, default=gen_uuid)
    memo_id = Column(String, nullable=False)       # FK to intelligence_memos
    ticker = Column(String(10), nullable=False)
    direction = Column(String(20))                  # from trade idea
    conviction = Column(Integer)
    entry_price = Column(Float)                     # price at signal time
    price_1d = Column(Float)                        # price 1 day later
    price_5d = Column(Float)                        # price 5 days later
    price_20d = Column(Float)                       # price 20 days later
    return_1d = Column(Float)                       # % return
    return_5d = Column(Float)
    return_20d = Column(Float)
    hit_direction_1d = Column(Boolean)              # did price move in predicted direction?
    hit_direction_5d = Column(Boolean)
    hit_direction_20d = Column(Boolean)
    scored_at = Column(DateTime, server_default=func.now())
```

### P7.2 — Backend: Scoring Job

**New file:** `backend/agents/scorer.py`

```python
async def score_pending_signals():
    """Score all signals that have aged enough but haven't been scored yet."""
```

Logic:
1. Query all `IntelligenceMemoRecord` with trade ideas
2. For each trade idea older than 1d (but not yet scored at 1d): fetch current price, compute return, store score
3. Same for 5d and 20d intervals
4. Compute aggregates: hit rate, average return, IC (using `signal_validation.py`)

Triggered via:
- `POST /api/scorecard/run` (manual trigger)
- Eventually: nightly cron job

### P7.3 — Backend: Scorecard Endpoints

**Modified:** `backend/main.py`

```python
GET  /api/scorecard/summary     # Aggregate: hit rate, IC, avg return per desk
GET  /api/scorecard/signals     # Individual signal scores with outcomes
POST /api/scorecard/run         # Trigger scoring of pending signals
```

### P7.4 — Frontend: Scorecard Tab

**Modified:** `frontend/app/portfolio/page.tsx`

New tab "Scorecard" (between Journal and Backtest):

**Summary cards:**
- Overall hit rate (1d / 5d / 20d)
- Information Coefficient
- Average return on winners vs losers
- Total signals scored

**Per-desk breakdown table:**
| Desk | Hit Rate (5d) | Avg Return | IC | Signals |
|------|---------------|------------|-----|---------|
| Research | 58% | +2.1% | 0.08 | 43 |
| Risk | 62% | +1.8% | 0.11 | 43 |

**Best/worst calls list:**
- Top 5 most profitable signals with details
- Bottom 5 worst signals with what went wrong

### P7 Deliverable

User goes to Portfolio → Scorecard tab → sees per-desk accuracy metrics, hit rates, and IC. Can see best and worst historical calls.

**Estimated scope:** ~100 lines scoring logic, ~60 lines endpoints, ~150 lines frontend tab. 1 new DB model.

---

## P8: P&L Attribution

**Goal:** Decompose portfolio returns into factor returns (beta, momentum, value) vs alpha (stock picking skill) vs noise. Show which desk contributes most to P&L.

### P8.1 — Backend: Attribution Endpoint

**Modified:** `backend/main.py`

```python
GET /api/portfolio/attribution    # P&L decomposition
```

Uses existing `quant/factors.py` (compute_factor_loadings, compute_multi_factor_loadings) and `quant/performance.py` (full_performance_report).

Logic:
1. Get all closed trades → compute realized returns series
2. Get all open trades → compute unrealized returns series
3. Combine into portfolio return series
4. Run factor decomposition: `compute_factor_loadings(portfolio_returns, SPY_returns)`
5. Return: alpha, beta, factor contributions, residual, per-period breakdown

### P8.2 — Frontend: Attribution Tab

**Modified:** `frontend/app/portfolio/page.tsx`

New tab "Attribution" (after Scorecard):

**Factor decomposition chart:**
- Stacked bar chart: total return broken into Market (beta), Momentum, Value, Size, Alpha, Residual
- Color-coded: factor returns in gray, alpha in green, residual in yellow

**Desk contribution** (requires P7 scorecard data):
- Bar chart showing P&L contribution per desk
- "Research desk signals generated +4.2% alpha, Risk desk prevented -2.1% in avoided losses"

### P8 Deliverable

User sees their portfolio return decomposed: "Of your 8.3% return, 5.1% was market beta, 2.4% was alpha from stock picking, and 0.8% was momentum factor."

**Estimated scope:** ~80 lines backend, ~120 lines frontend. Uses existing quant modules.

---

## Dependency Graph

```
P1 (Tracing) ──────────────────────────────┐
                                           ├──→ P4 (Agent Split) depends on P1 trace format
P2 (Scanning) ─────────────────────────────┘
                                           
P3 (P&L/Positions) ───────────────────────→ standalone, no dependencies

P4 (Agent Split) ──→ P5 (Risk Gates) ──→ P6 (Decision Gate)

P3 (Positions) + P7 (Scorecard) ──→ P8 (Attribution)
```

**Can be built in parallel:**
- P1 + P3 (tracing + positions — independent)
- P2 can start after P1 (scanner uses same SSE infrastructure)
- P5 + P6 can be done together after P4
- P7 + P8 can be done together after P3

---

## Files Changed Summary

| Priority | New Files | Modified Files | New Models |
|----------|-----------|---------------|------------|
| P1 | `agents/stream_callbacks.py` | `agents/base_agent.py`, `agents/query_interpreter.py`, `agents/cio_synthesizer.py`, `main.py`, `useAnalysis.ts`, `AnalysisTrace.tsx` | None |
| P2 | `agents/scanner.py`, `agents/universe.py`, `ScanFindings.tsx` | `db/models.py`, `main.py`, `api.ts`, `page.tsx` (Home) | `ScanFindingRecord`, `ScanRunRecord`, `WatchlistRecord` |
| P3 | None | `main.py`, `portfolio/page.tsx`, `api.ts` | None |
| P4 | `desk2_data_analyst.py`, `desk2_thesis_builder.py`, `desk3_macro_regime.py`, `desk3_position_risk.py`, `desk4_trade_structurer.py`, `desk4_hedge_architect.py`, `desk5_memo_writer.py`, `desk5_decision_gate.py` | `orchestrator.py`, `main.py` | None |
| P5 | None | `main.py`, `MemoPanel.tsx`, `portfolio/page.tsx` | None |
| P6 | None | `main.py`, `MemoPanel.tsx`, `useAnalysis.ts` | None |
| P7 | `agents/scorer.py` | `db/models.py`, `main.py`, `portfolio/page.tsx`, `api.ts` | `SignalScoreRecord` |
| P8 | None | `main.py`, `portfolio/page.tsx`, `api.ts` | None |

---

## Success Criteria

| Priority | Done When |
|----------|-----------|
| P1 | User sees tool calls, data summaries, and risk decisions streaming in real time during analysis |
| P2 | User opens app and sees flagged tickers without clicking anything. "Analyze →" jumps to analysis with auto-submit |
| P3 | Portfolio page shows aggregated positions with live P&L, summary cards show total value and unrealized return |
| P4 | 12 agents across 6 desks, trace shows desk breakdown, same memo quality or better |
| P5 | Taking a trade that breaches risk limits returns a clear "BLOCKED" message with reasons |
| P6 | Every memo has a GO/NO-GO/WATCH badge at the top |
| P7 | Portfolio → Scorecard tab shows per-desk hit rate, IC, and best/worst calls |
| P8 | Portfolio → Attribution tab shows factor decomposition of returns |
