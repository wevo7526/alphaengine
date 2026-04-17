"""
Alpha Engine schemas — structured types for the hedge fund research desk pipeline.

Pipeline: Query Interpreter → Research Analyst → Risk Manager → Portfolio Strategist → CIO Synthesizer
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime, timezone


# All schemas use extra="ignore" because LLM outputs frequently include
# unexpected fields. Without this, Pydantic throws ValidationError and
# the streaming pipeline dies silently.


# === Query Classification ===

class QueryIntent(str, Enum):
    TICKER_ANALYSIS = "ticker_analysis"
    THEMATIC_RESEARCH = "thematic_research"
    RISK_ASSESSMENT = "risk_assessment"
    PORTFOLIO_IDEAS = "portfolio_ideas"
    MARKET_REGIME = "market_regime"


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

    """Structured output from the Research Analyst."""
    macro_data: Optional[dict] = None
    ticker_data: dict[str, dict] = Field(default_factory=dict)
    news_data: list[dict] = Field(default_factory=list)
    filing_data: list[dict] = Field(default_factory=list)
    thematic_data: dict = Field(default_factory=dict)
    data_summary: str = ""


# === Risk Assessment ===

class RiskFactor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = ""
    description: str = ""
    severity: str = "medium"
    probability: str = "medium"
    mitigation: str = ""


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """Output from the Risk Manager."""
    macro_regime: str = "unknown"
    regime_confidence: int = Field(default=50, ge=0, le=100)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    overall_risk_level: str = "elevated"
    risk_narrative: str = ""


# === Trade Ideas ===

class SignalDirection(str, Enum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


# Map common LLM synonyms to valid enum values
_DIRECTION_ALIASES = {
    "long": "bullish",
    "short": "bearish",
    "buy": "bullish",
    "sell": "bearish",
    "strong_buy": "strong_bullish",
    "strong_sell": "strong_bearish",
    "strong buy": "strong_bullish",
    "strong sell": "strong_bearish",
    "hold": "neutral",
    "overweight": "bullish",
    "underweight": "bearish",
}


class TradeIdea(BaseModel):
    model_config = ConfigDict(extra="ignore")

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

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, v):
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in _DIRECTION_ALIASES:
                return _DIRECTION_ALIASES[v_lower]
        return v

    @field_validator("conviction", mode="before")
    @classmethod
    def clamp_conviction(cls, v):
        try:
            v = int(v)
            return max(0, min(100, v))
        except (ValueError, TypeError):
            return 50

    @field_validator("stop_loss", "take_profit", "risk_reward_ratio", mode="before")
    @classmethod
    def coerce_float(cls, v):
        if v is None or v == "" or v == "N/A" or v == "n/a":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


class PortfolioStrategy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """Output from the Portfolio Strategist."""
    trade_ideas: list[TradeIdea] = Field(default_factory=list)
    portfolio_positioning: str = "neutral"
    hedging_recommendations: list[str] = Field(default_factory=list)
    strategy_narrative: str = ""


# === Final Output ===

class IntelligenceMemo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """The final CIO-level intelligence memo with trade ideas."""
    query: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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
    # Desk 5B: Decision Gate — programmatic GO/NO-GO
    decision: str = "WATCH"  # GO | NO-GO | WATCH
    decision_reason: str = ""
    decision_confidence: int = 0

    @field_validator("intent", mode="before")
    @classmethod
    def coerce_intent(cls, v):
        if isinstance(v, str):
            try:
                return QueryIntent(v)
            except ValueError:
                return QueryIntent.THEMATIC_RESEARCH
        return v


# === Internal Agent Output ===

class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """Generic internal agent output for pipeline state."""
    agent_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    output: dict = Field(default_factory=dict)
    reasoning: str = ""
    error: Optional[str] = None
