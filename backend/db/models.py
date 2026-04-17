"""
SQLAlchemy ORM models for Alpha Engine.

Adapted from the spec's Section 9 schema for the restructured
hedge fund research desk architecture.
"""

from sqlalchemy import Column, String, Integer, Float, Text, Boolean, DateTime, Date, JSON
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
    created_at = Column(DateTime, server_default=func.now())


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
    created_at = Column(DateTime, server_default=func.now())


class PortfolioSnapshotRecord(Base):
    """Point-in-time portfolio state for equity curve tracking."""
    __tablename__ = "portfolio_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    snapshot_date = Column(Date, nullable=False, unique=True)
    total_value = Column(Float)
    cash = Column(Float)
    positions_value = Column(Float)
    daily_pnl = Column(Float)
    daily_pnl_pct = Column(Float)
    cumulative_pnl = Column(Float)
    cumulative_pnl_pct = Column(Float)
    positions_json = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())


class FactorExposureRecord(Base):
    """Rolling factor loadings computed from portfolio returns."""
    __tablename__ = "factor_exposures"

    id = Column(String, primary_key=True, default=gen_uuid)
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
    created_at = Column(DateTime, server_default=func.now())


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
    created_at = Column(DateTime, server_default=func.now())


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
    created_at = Column(DateTime, server_default=func.now())


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
    opened_at = Column(DateTime, server_default=func.now())
    closed_at = Column(DateTime)


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
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class MacroSnapshotRecord(Base):
    """Historical macro regime snapshots for tracking regime changes."""
    __tablename__ = "macro_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    regime = Column(String(20), nullable=False)
    regime_confidence = Column(Integer)
    risk_level = Column(String(20))
    indicators = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


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
    created_at = Column(DateTime, server_default=func.now())


class ScanRunRecord(Base):
    """A single execution of the universe scanner."""
    __tablename__ = "scan_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    universe_size = Column(Integer)
    findings_count = Column(Integer, default=0)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    status = Column(String(20), default="running")  # running, completed, failed
    error_message = Column(Text)


class WatchlistRecord(Base):
    """User's watchlist tickers — included in universe scans."""
    __tablename__ = "watchlist"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    ticker = Column(String(10), nullable=False)
    notes = Column(Text)
    added_at = Column(DateTime, server_default=func.now())


class MorningReportRecord(Base):
    """Pre-market morning briefings, one per day."""
    __tablename__ = "morning_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, nullable=True, index=True)
    report_date = Column(String(10), nullable=False, unique=True)  # YYYY-MM-DD
    executive_briefing = Column(Text)
    macro_regime = Column(String(20))
    key_macro_changes = Column(JSON, default=list)
    risk_alerts = Column(JSON, default=list)
    overnight_opportunities = Column(JSON, default=list)
    full_report = Column(JSON)  # Complete report data
    created_at = Column(DateTime, server_default=func.now())
