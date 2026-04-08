"""
SQLAlchemy ORM models for Alpha Engine.

Adapted from the spec's Section 9 schema for the restructured
hedge fund research desk architecture.
"""

from sqlalchemy import Column, String, Integer, Float, Text, Boolean, DateTime, JSON
from sqlalchemy.sql import func
import uuid

from db.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class IntelligenceMemoRecord(Base):
    """Persisted intelligence memos from the research desk pipeline."""
    __tablename__ = "intelligence_memos"

    id = Column(String, primary_key=True, default=gen_uuid)
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


class MorningReportRecord(Base):
    """Pre-market morning briefings, one per day."""
    __tablename__ = "morning_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    report_date = Column(String(10), nullable=False, unique=True)  # YYYY-MM-DD
    executive_briefing = Column(Text)
    macro_regime = Column(String(20))
    key_macro_changes = Column(JSON, default=list)
    risk_alerts = Column(JSON, default=list)
    overnight_opportunities = Column(JSON, default=list)
    full_report = Column(JSON)  # Complete report data
    created_at = Column(DateTime, server_default=func.now())
