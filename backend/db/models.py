"""
SQLAlchemy ORM models for Alpha Engine.

Adapted from the spec's Section 9 schema for the restructured
hedge fund research desk architecture.
"""

from sqlalchemy import Column, String, Integer, Float, Text, Boolean, DateTime, Date, JSON, Index
from sqlalchemy.sql import func
import uuid

from db.database import Base


def gen_uuid():
    return str(uuid.uuid4())


# ============================================================
# NEW QUANT INFRASTRUCTURE MODELS (Phase 2-4)
# ============================================================


class BacktestRunRecord(Base):
    """Configuration and metadata for a backtest run."""
    __tablename__ = "backtest_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    name = Column(String(200))
    tickers = Column(JSON, default=list)
    start_date = Column(Date)
    end_date = Column(Date)
    initial_capital = Column(Float, default=100000)
    strategy_config = Column(JSON, default=dict)
    mode = Column(String(30), default="rules_based")  # rules_based / signal_replay
    status = Column(String(20), default="pending")  # pending / running / completed / failed
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BacktestResultRecord(Base):
    """Results from a completed backtest run."""
    __tablename__ = "backtest_results"

    id = Column(String, primary_key=True, default=gen_uuid)
    backtest_run_id = Column(String, nullable=False)
    equity_curve = Column(JSON, default=list)
    drawdown_series = Column(JSON, default=list)
    sharpe_ratio = Column(Float)
    sortino_ratio = Column(Float)
    calmar_ratio = Column(Float)
    max_drawdown_pct = Column(Float)
    max_drawdown_duration_days = Column(Integer)
    total_return_pct = Column(Float)
    annualized_return_pct = Column(Float)
    win_rate = Column(Float)
    profit_factor = Column(Float)
    total_trades = Column(Integer)
    avg_trade_pnl_pct = Column(Float)
    avg_holding_days = Column(Float)
    trades = Column(JSON, default=list)
    benchmark_return_pct = Column(Float)
    benchmark_sharpe = Column(Float)
    factor_exposures = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PortfolioSnapshotRecord(Base):
    """Point-in-time portfolio state for equity curve tracking.

    One row per (user_id, snapshot_date). The EOD snapshot job upserts —
    rerunning the same day overwrites instead of duplicating.
    """
    __tablename__ = "portfolio_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    snapshot_date = Column(Date, nullable=False)
    total_value = Column(Float)
    cash = Column(Float)
    positions_value = Column(Float)
    daily_pnl = Column(Float)
    daily_pnl_pct = Column(Float)
    cumulative_pnl = Column(Float)
    cumulative_pnl_pct = Column(Float)
    positions_json = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_portfolio_snapshots_user_date", "user_id", "snapshot_date", unique=True),
    )


class PositionSnapshotRecord(Base):
    """Per-position EOD state. Lets us reconstruct contribution to the
    portfolio's equity curve and render per-position pnl sparklines.

    One row per (trade_id, snapshot_date). Upserted by the EOD snapshot
    job so reruns on the same day are safe.
    """
    __tablename__ = "position_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    trade_id = Column(String, nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(20), nullable=True)
    snapshot_date = Column(Date, nullable=False)
    entry_price = Column(Float)
    close_price = Column(Float)
    position_size_pct = Column(Float)
    unrealized_pnl_pct = Column(Float)
    unrealized_pnl_dollars = Column(Float)
    market_value = Column(Float)
    cost_basis = Column(Float)
    days_held = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_position_snapshots_user_date", "user_id", "snapshot_date"),
        Index("ix_position_snapshots_trade_date", "trade_id", "snapshot_date", unique=True),
    )


class FactorExposureRecord(Base):
    """Rolling factor loadings computed from portfolio returns."""
    __tablename__ = "factor_exposures"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    computation_date = Column(Date, nullable=False)
    market_beta = Column(Float)
    smb_beta = Column(Float)  # Size
    hml_beta = Column(Float)  # Value
    rmw_beta = Column(Float)  # Profitability
    cma_beta = Column(Float)  # Investment
    mom_beta = Column(Float)  # Momentum
    alpha = Column(Float)
    alpha_tstat = Column(Float)
    r_squared = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RegimeRecord(Base):
    """HMM-detected macro regime states."""
    __tablename__ = "regime_states"

    id = Column(String, primary_key=True, default=gen_uuid)
    detection_date = Column(Date, nullable=False)
    current_regime = Column(String(30))
    expansion_prob = Column(Float)
    late_cycle_prob = Column(Float)
    contraction_prob = Column(Float)
    recovery_prob = Column(Float)
    confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# PROVENANCE LAYER (Build Plan Phase 1) — evidence receipts
# ============================================================


class EvidenceRecord(Base):
    """A provenance receipt — the atomic unit of traceability.

    Two kinds (Build Plan §1.1):
      - kind='computed': a number the engine produced (correlation, VaR,
        Sharpe, P/E, beta, IV skew, a conviction sub-score). Stores the
        metric name, the value, the inputs, the formula/function reference,
        and the upstream source(s).
      - kind='source': a qualitative claim grounded in retrieved text
        (filing language, news, transcript). Stores the source ref
        (URL / EDGAR accession), the verbatim passage (≤ a few sentences),
        and a content hash.

    Deduplicated by `content_hash` (unique): the same datum fetched or
    computed twice upserts to one row. This doubles as a persistent,
    content-hash-keyed cache so re-running the same query reuses evidence
    instead of re-hitting a paid API (Build Plan §1.2 + Cost Discipline).
    """
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=gen_uuid)
    kind = Column(String(10), nullable=False)  # computed | source
    # Provenance
    source_name = Column(String(60))   # fred | yahoo | sec | newsapi | finnhub | firecrawl | alpha_vantage | engine
    source_ref = Column(Text)          # URL / EDGAR accession / API endpoint / function ref
    # Source receipts
    passage = Column(Text, nullable=True)        # verbatim extracted text
    retrieved_at = Column(DateTime(timezone=True), nullable=True)
    # Computed receipts
    metric = Column(String(120), nullable=True)
    value_json = Column(JSON, nullable=True)     # the computed value (number / small object)
    inputs_json = Column(JSON, nullable=True)    # input series identifiers / params
    formula_ref = Column(String(160), nullable=True)  # e.g. "quant.risk.parametric_var"
    # Dedup / cache key — stable hash over the receipt's defining content.
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    # Optional scoping for retrieval + cache reuse.
    ticker = Column(String(20), nullable=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_evidence_ticker_kind", "ticker", "kind"),
    )


class TrackRecordAnchor(Base):
    """Tamper-evident anchor for the forward track record (Build Plan §3.3).

    Periodically we chain every scored signal (ordered by signal_date, id) and
    store the chain head here. Re-chaining later and comparing to the latest
    anchor makes any silent edit / reorder / deletion of a historical scored
    signal detectable — the recomputed head won't match. Append-only: we never
    update an anchor, only add new ones.
    """
    __tablename__ = "track_record_anchors"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    anchored_at = Column(DateTime(timezone=True), server_default=func.now())
    n_records = Column(Integer, default=0)
    head_hash = Column(String(64), nullable=False)
    prev_anchor_hash = Column(String(64), nullable=True)  # chains the anchors themselves


class ClaimEvidenceRecord(Base):
    """Join table — a claim in a memo cites one or more evidence rows.

    `claim_ref` identifies the cited claim within the memo: a structured
    field (e.g. "trade_idea:AAPL:entry_price", "risk_factor:2"), an inline
    prose anchor (e.g. "analysis:offset:1420"), or a key-finding index.
    A single claim may cite multiple evidence rows (M:N).
    """
    __tablename__ = "claim_evidence"

    id = Column(String, primary_key=True, default=gen_uuid)
    memo_id = Column(String, nullable=True, index=True)
    claim_ref = Column(String(200), nullable=False)
    evidence_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_claim_evidence_memo", "memo_id", "claim_ref"),
    )


# ============================================================
# EXISTING MODELS (unchanged)
# ============================================================


class IntelligenceMemoRecord(Base):
    """Persisted intelligence memos from the research desk pipeline."""
    __tablename__ = "intelligence_memos"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    query = Column(Text, nullable=False)
    intent = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)
    executive_summary = Column(Text, nullable=False)
    analysis = Column(Text)
    key_findings = Column(JSON, default=list)
    macro_regime = Column(String(20))
    overall_risk_level = Column(String(20))
    risk_factors = Column(JSON, default=list)
    trade_ideas = Column(JSON, default=list)
    portfolio_positioning = Column(String(50))
    hedging_recommendations = Column(JSON, default=list)
    tickers_analyzed = Column(JSON, default=list)
    themes = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Phase D provenance — structured record of every tool call that produced
    # data for this memo. Shape: {sources: [{tool, args, source_id, source_type,
    # evidence_url}], by_tool: {tool_name: count}, by_source_type: {...}}.
    # Surfaced to the UI as a "View sources" panel so a PM can audit any claim.
    lineage = Column(JSON, default=dict)
    # Phase E — conversational thread layer. A research thread is an ordered
    # chain of memos. First memo: thread_id = its own id, parent_memo_id = NULL,
    # sequence = 0. Follow-up memos inherit thread_id, set parent_memo_id to
    # the immediately preceding memo, increment sequence. thread_summary is a
    # compressed running narrative the CIO can read to maintain continuity.
    thread_id = Column(String, nullable=True, index=True)
    parent_memo_id = Column(String, nullable=True, index=True)
    sequence_in_thread = Column(Integer, default=0)
    thread_summary = Column(Text, nullable=True)
    # Query class (fresh | drilldown_ticker | drilldown_theme | risk_check |
    # validation | time_horizon_shift | comparison). Set by the Interpreter
    # so the consumer can show which kind of follow-up produced the memo.
    query_class = Column(String(40), nullable=True)
    # Phase G — claim-level citations.
    # citation_index: deduplicated, numbered list of every Citation
    # referenced across trade_ideas, risk_factors, and inline `[N]`
    # markers in `analysis` prose. Each entry: {n, source_type, source_id,
    # url, label, excerpt}. Citations on trade_ideas / risk_factors are
    # stored in-place inside their respective JSON columns above.
    citation_index = Column(JSON, default=list)
    # coverage: {citation_coverage_pct, claim_coverage_pct, trade_ideas_cited,
    # trade_ideas_total, risk_factors_cited, risk_factors_total,
    # numeric_claims, inline_anchors}
    coverage = Column(JSON, default=dict)
    # verification_status: "verified" | "partial" | "unverified". Drives
    # the VERIFIED pill on the memo header. Defaults to "unverified" for
    # older memos persisted before this column existed.
    verification_status = Column(String(20), default="unverified")

    # /api/signals/latest filters by user_id ordered by created_at desc.
    # Without this composite, every call scans the whole table.
    __table_args__ = (
        Index("ix_memos_user_created", "user_id", "created_at"),
    )


class TradeRecord(Base):
    """Trade journal — CIO decisions on trade ideas."""
    __tablename__ = "trades"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    memo_id = Column(String, nullable=True)  # FK to intelligence_memos.id
    ticker = Column(String(10), nullable=False)
    direction = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)  # BUY, SELL, SHORT, COVER
    entry_price = Column(Float)
    quantity = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    position_size_pct = Column(Float)
    conviction = Column(Integer)
    thesis = Column(Text)
    md_notes = Column(Text)
    status = Column(String(20), default="open")  # open, closed, stopped_out
    exit_price = Column(Float)
    realized_pnl = Column(Float)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))
    # Phase E — working-order tracking. Orthogonal to `status` (trade lifecycle).
    # active   = PM is actively working this idea
    # shelved  = deprioritized, may revisit
    # dismissed = explicitly rejected, hide from the active book
    working_status = Column(String(20), default="active")
    watchlist_id = Column(String, nullable=True, index=True)

    # /api/portfolio/positions filters by user_id + status (open), and memo_id
    # joins are common. Indexes sized for the actual query shape.
    __table_args__ = (
        Index("ix_trades_user_status", "user_id", "status"),
        Index("ix_trades_memo", "memo_id"),
    )


class PortfolioPosition(Base):
    """Current portfolio state."""
    __tablename__ = "portfolio"

    id = Column(String, primary_key=True, default=gen_uuid)
    ticker = Column(String(10), nullable=False, unique=True)
    quantity = Column(Float, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    current_price = Column(Float)
    unrealized_pnl = Column(Float)
    weight = Column(Float)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserProfile(Base):
    """
    Lightweight per-user profile captured during onboarding.

    Holds the operational defaults a PM picks when they first sign up:
    role, paper portfolio size for sizing math, benchmark for relative
    performance, and investment mandate (long-only / L/S / market-neutral
    / macro / multi-strat). `onboarded_at` is set when the user completes
    the onboarding flow; null means they have not finished yet and the
    SessionGuard should route them to /onboarding.

    This is intentionally minimal — full firm / pod / multi-tenant
    structure lands in Tranche 1 of the production refactor. For now,
    every user has one solo profile.
    """
    __tablename__ = "user_profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=False, unique=True, index=True)
    full_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    role = Column(String(30), nullable=True)            # pm | analyst | allocator | other
    portfolio_size_usd = Column(Float, nullable=True)
    benchmark = Column(String(20), default="SPY")
    mandate = Column(String(30), default="long_short")  # long_only|long_short|market_neutral|macro|multi_strat
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    onboarded_at = Column(DateTime(timezone=True), nullable=True)


class UserRiskProfile(Base):
    """
    Per-user overrides for the platform's risk gates.

    Each column mirrors a constant in `quant.limits`. NULL means "use the
    platform default" — concretely, the limit resolution order at trade
    time is: user override (this row) -> env var -> hardcoded default in
    quant/limits.py.

    Why a sibling table instead of extending UserProfile: 17 risk
    parameters with validation rules deserve their own surface (separate
    /risk-config page). Keeping them in their own table makes the
    onboarding flow simpler and keeps profile updates from accidentally
    touching risk overrides.
    """
    __tablename__ = "user_risk_profiles"

    user_id = Column(String, primary_key=True, index=True)

    # Position limits (decimals: 0.05 = 5%)
    max_position_pct = Column(Float, nullable=True)
    max_sector_pct = Column(Float, nullable=True)
    min_position_pct = Column(Float, nullable=True)

    # VaR / circuit breaker
    var_confidence = Column(Float, nullable=True)
    drawdown_caution_pct = Column(Float, nullable=True)
    drawdown_warn_pct = Column(Float, nullable=True)
    drawdown_critical_pct = Column(Float, nullable=True)

    # Marginal VaR / silent-squeeze
    marginal_var_block_pct = Column(Float, nullable=True)
    silent_squeeze_threshold = Column(Float, nullable=True)

    # Liquidity
    liquidity_max_pct_of_adv = Column(Float, nullable=True)
    liquidity_block_pct_of_adv = Column(Float, nullable=True)
    liquidity_participation_rate = Column(Float, nullable=True)
    liquidity_spread_warn_bps = Column(Float, nullable=True)

    # Optimizer
    optimizer_tx_cost_bps = Column(Float, nullable=True)
    optimizer_ridge_lambda = Column(Float, nullable=True)

    # Factor
    vif_max_threshold = Column(Float, nullable=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MacroSnapshotRecord(Base):
    """Historical macro regime snapshots for tracking regime changes."""
    __tablename__ = "macro_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    regime = Column(String(20), nullable=False)
    regime_confidence = Column(Integer)
    risk_level = Column(String(20))
    indicators = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScanFindingRecord(Base):
    """Individual finding from an overnight/on-demand universe scan."""
    __tablename__ = "scan_findings"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    scan_run_id = Column(String, nullable=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    finding_type = Column(String(30), nullable=False)
    # Types: insider_cluster, earnings_surprise, momentum_break, rsi_extreme,
    #        volume_spike, sentiment_shift, macro_shift, filing_alert, ma_crossover
    priority = Column(String(10), nullable=False, index=True)  # high, medium, low
    headline = Column(String(200), nullable=False)
    detail = Column(Text)
    data_json = Column(JSON)  # Raw anomaly data for drill-down
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScanRunRecord(Base):
    """A single execution of the universe scanner."""
    __tablename__ = "scan_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    universe_size = Column(Integer)
    findings_count = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="running")  # running, completed, failed
    error_message = Column(Text)


class SignalScoreRecord(Base):
    """Track every past trade idea at 1d/5d/20d intervals to measure signal quality."""
    __tablename__ = "signal_scores"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    memo_id = Column(String, nullable=True, index=True)  # FK to intelligence_memos
    ticker = Column(String(10), nullable=False, index=True)
    direction = Column(String(20))  # from trade idea
    conviction = Column(Integer)
    entry_price = Column(Float)          # Price at signal time
    signal_date = Column(DateTime(timezone=True))        # When the memo was created

    # Forward prices at different intervals
    price_1d = Column(Float)
    price_5d = Column(Float)
    price_20d = Column(Float)

    # Returns (signed — positive means the direction was correct)
    return_1d = Column(Float)             # % return in predicted direction
    return_5d = Column(Float)
    return_20d = Column(Float)

    # Hit flags (was the direction correct?)
    hit_1d = Column(Boolean)
    hit_5d = Column(Boolean)
    hit_20d = Column(Boolean)

    scored_at = Column(DateTime(timezone=True), server_default=func.now())

    # Scorecard queries filter by user_id and order by signal_date desc.
    __table_args__ = (
        Index("ix_signal_scores_user_date", "user_id", "signal_date"),
    )


class WatchlistRecord(Base):
    """User's watchlist tickers — included in universe scans."""
    __tablename__ = "watchlist"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    ticker = Column(String(10), nullable=False)
    notes = Column(Text)
    added_at = Column(DateTime(timezone=True), server_default=func.now())


class MorningReportRecord(Base):
    """Pre-market morning briefings — one per user per day."""
    __tablename__ = "morning_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    report_date = Column(String(10), nullable=False)  # YYYY-MM-DD (unique per user — app-level check)
    executive_briefing = Column(Text)
    macro_regime = Column(String(20))
    key_macro_changes = Column(JSON, default=list)
    risk_alerts = Column(JSON, default=list)
    overnight_opportunities = Column(JSON, default=list)
    full_report = Column(JSON)  # Complete report data
    created_at = Column(DateTime(timezone=True), server_default=func.now())
