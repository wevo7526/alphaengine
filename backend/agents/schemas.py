"""
Alpha Engine schemas — structured types for the hedge fund research desk pipeline.

Pipeline: Query Interpreter → Research Analyst → Risk Manager → Portfolio Strategist → CIO Synthesizer
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


# === Query Classification ===

class QueryIntent(str, Enum):
    TICKER_ANALYSIS = "ticker_analysis"
    THEMATIC_RESEARCH = "thematic_research"
    RISK_ASSESSMENT = "risk_assessment"
    PORTFOLIO_IDEAS = "portfolio_ideas"
    MARKET_REGIME = "market_regime"


class AnalysisPlan(BaseModel):
    """Output of the Query Interpreter — the research plan."""
    query: str
    intent: QueryIntent
    tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    data_requests: list[str] = Field(
        default_factory=list,
        description="Specific instructions for the Research Analyst",
    )
    risk_focus: list[str] = Field(default_factory=list)
    time_horizon: str = Field(default="weeks")


# === Research Data ===

class ResearchData(BaseModel):
    """Structured output from the Research Analyst."""
    macro_data: Optional[dict] = None
    ticker_data: dict[str, dict] = Field(default_factory=dict)
    news_data: list[dict] = Field(default_factory=list)
    filing_data: list[dict] = Field(default_factory=list)
    thematic_data: dict = Field(default_factory=dict)
    data_summary: str = ""


# === Risk Assessment ===

class RiskFactor(BaseModel):
    category: str = ""
    description: str = ""
    severity: str = "medium"
    probability: str = "medium"
    mitigation: str = ""


class RiskAssessment(BaseModel):
    """Output from the Risk Manager."""
    macro_regime: str = "unknown"
    regime_confidence: int = Field(default=50, ge=0, le=100)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    overall_risk_level: str
    risk_narrative: str = ""


# === Trade Ideas ===

class SignalDirection(str, Enum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


class TradeIdea(BaseModel):
    ticker: str = ""
    direction: SignalDirection = SignalDirection.NEUTRAL
    conviction: int = Field(default=50, ge=0, le=100)
    thesis: str = ""
    entry_zone: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    position_size_pct: float = 0
    time_horizon: str = "weeks"
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class PortfolioStrategy(BaseModel):
    """Output from the Portfolio Strategist."""
    trade_ideas: list[TradeIdea] = Field(default_factory=list)
    portfolio_positioning: str = "neutral"
    hedging_recommendations: list[str] = Field(default_factory=list)
    strategy_narrative: str = ""


# === Final Output ===

class IntelligenceMemo(BaseModel):
    """The final CIO-level intelligence memo with trade ideas."""
    query: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    title: str = ""
    executive_summary: str = ""
    analysis: str = ""
    key_findings: list[str] = Field(default_factory=list)
    macro_regime: str = ""
    overall_risk_level: str = ""
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    trade_ideas: list[TradeIdea] = Field(default_factory=list)
    portfolio_positioning: str = ""
    hedging_recommendations: list[str] = Field(default_factory=list)
    tickers_analyzed: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    intent: QueryIntent = QueryIntent.THEMATIC_RESEARCH


# === Internal Agent Output ===

class AgentOutput(BaseModel):
    """Generic internal agent output for pipeline state."""
    agent_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    output: dict = Field(default_factory=dict)
    reasoning: str = ""
    error: Optional[str] = None
