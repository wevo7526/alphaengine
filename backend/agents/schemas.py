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


class QuestionType(str, Enum):
    """Analytical shape of the query. Distinct from `intent` (which desk to engage)."""
    ALPHA_FINDING = "alpha_finding"        # discover edge ("best risk-adjusted trade")
    HEDGING = "hedging"                    # protect against risk ("how to hedge X?")
    REGIME_CHECK = "regime_check"          # macro outlook ("late-cycle here?")
    VALUATION = "valuation"                # is it cheap? ("AAPL overvalued at 32x?")
    COMPARISON = "comparison"              # relative value ("MSFT vs GOOGL?")
    FACTOR_EXPOSURE = "factor_exposure"    # beta/style ("how exposed to growth?")
    PAIR_TRADE = "pair_trade"              # relative positioning
    POST_MORTEM = "post_mortem"            # analyze past outcome
    WHAT_IF = "what_if"                    # scenario analysis


class InstrumentPreference(str, Enum):
    """How the Strategist should structure the trade."""
    STOCK = "stock"
    OPTIONS = "options"
    PAIR_TRADE = "pair_trade"
    SPREAD = "spread"
    HEDGE = "hedge"
    MIXED = "mixed"


class DataPriorityItem(BaseModel):
    """One ranked instruction for the Research Analyst."""
    model_config = ConfigDict(extra="ignore")
    rank: int = Field(default=3, ge=1, le=4)  # 1=critical, 4=skip
    data_source: str = ""  # "sec_filings", "fundamentals", "options", "macro", "news", "analyst_consensus", "skip"
    query: str = ""        # specific instruction
    justification: str = ""


class RegimeSensitivity(BaseModel):
    """How the thesis changes per macro regime."""
    model_config = ConfigDict(extra="ignore")
    regime: str = ""  # "expansion" | "late_cycle" | "contraction" | "recovery"
    ideal_position: str = ""
    conviction_multiplier: float = Field(default=1.0, ge=0.0, le=1.5)
    key_assumption: str = ""


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """Output of the Query Interpreter — the research plan that everything cascades off."""
    query: str
    intent: QueryIntent
    tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    data_requests: list[str] = Field(
        default_factory=list,
        description="Legacy free-text instructions; superseded by data_priority but kept for backward compat",
    )
    risk_focus: list[str] = Field(default_factory=list)
    time_horizon: str = Field(default="weeks")
    plan_confidence: int = Field(default=70, ge=0, le=100)
    plan_confidence_reason: str = Field(default="")

    # === Phase-2 enrichment fields — these are what makes the plan tailored ===

    # The analytical shape of the question
    question_type: QuestionType = QuestionType.ALPHA_FINDING

    # 3-6 specific questions the Research Analyst MUST answer in data_summary.
    # Used by Research's completeness check + cited by name in the CIO memo.
    sub_questions: list[str] = Field(default_factory=list)

    # Tickers explicitly named for benchmark/relative valuation, NOT trade ideas.
    # Strategist uses these as a yardstick; Research calls peer_comparison with them.
    comparison_set: list[str] = Field(default_factory=list)

    # Ranked data fetch plan — overrides data_requests when present.
    data_priority: list[DataPriorityItem] = Field(default_factory=list)

    # Concrete data points that would invalidate the thesis. Risk Manager scores
    # them; CIO frames "what would change our view" in the memo.
    falsification_criteria: list[str] = Field(default_factory=list)

    # Theme broken into sub-components ("AI capex" → {hyperscaler_capex_levels,
    # training_vs_inference_mix, ...}). Research structures data_summary around it.
    theme_decomposition: dict[str, list[str]] = Field(default_factory=dict)

    # What this trade should beat (ETF or index ticker, e.g. "SMH" or "SPY")
    benchmark: str = ""

    # How the thesis varies by regime. Strategist sizes per regime; Decision Gate
    # uses to override conviction if regime opposite to ideal.
    regime_sensitivity: list[RegimeSensitivity] = Field(default_factory=list)

    # Stock vs options vs pair trade vs spread vs hedge vs mixed.
    # Steers the Strategist away from "all 5 outright longs" default.
    instrument_preference: InstrumentPreference = InstrumentPreference.STOCK

    # Structural diversity directive: e.g., ["3 longs", "1 pair_trade", "1 hedge"].
    # Strategist diversity validator enforces against this.
    idea_archetype: list[str] = Field(default_factory=list)

    @field_validator("question_type", mode="before")
    @classmethod
    def coerce_question_type(cls, v):
        if isinstance(v, str):
            try:
                return QuestionType(v.strip().lower())
            except ValueError:
                return QuestionType.ALPHA_FINDING
        return v

    @field_validator("instrument_preference", mode="before")
    @classmethod
    def coerce_instrument(cls, v):
        if isinstance(v, str):
            try:
                return InstrumentPreference(v.strip().lower())
            except ValueError:
                return InstrumentPreference.STOCK
        return v


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


class FalsificationScore(BaseModel):
    """Risk Manager's probability assessment for each plan.falsification_criterion."""
    model_config = ConfigDict(extra="ignore")
    criterion: str = ""
    probability: str = "medium"  # low | medium | high
    reasoning: str = ""


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """Output from the Risk Manager."""
    macro_regime: str = "unknown"
    regime_confidence: int = Field(default=50, ge=0, le=100)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    overall_risk_level: str = "elevated"
    risk_narrative: str = ""
    # New: per-criterion probability scoring against plan.falsification_criteria
    falsification_probabilities: list[FalsificationScore] = Field(default_factory=list)


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
    # Set by the server-side validator when entry/stop/target were
    # auto-corrected to anchor against live price. Surfaced as a UI badge.
    price_corrected: bool = False
    live_price_used: Optional[float] = None
    original_entry_zone: Optional[str] = None
    # Beta layering — systematic exposure decomposition
    beta_to_spy: Optional[float] = None
    sector: Optional[str] = None
    regime_conditional_size_pct: Optional[float] = None
    # Trade structure (set by Strategist when instrument_preference != stock)
    structure_type: Optional[str] = None  # "outright" | "pair" | "spread" | "calls" | "puts" | "hedge"
    pair_short_leg: Optional[str] = None  # ticker if this is a pair_trade

    @field_validator("price_corrected", mode="before")
    @classmethod
    def _coerce_corrected(cls, v):
        # Validator emits "_price_corrected" prefixed key; map both spellings.
        return bool(v) if v is not None else False

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
    # Provenance / quality signals — surfaced in the UI as small badges,
    # never persisted to the memo DB record (set in orchestrator post-run).
    grounding: dict = Field(default_factory=dict)  # {confidence, ungrounded_count, ...}
    plan_confidence: int = 0
    plan_confidence_reason: str = ""
    # New: end-to-end pipeline quality + structural integrity signals
    data_quality: str = "complete"  # complete | degraded | critical
    sub_question_coverage: list[dict] = Field(default_factory=list)
    sub_question_answered_pct: Optional[float] = None
    diversity: dict = Field(default_factory=dict)  # {monolithic, reason, direction_split, ...}
    falsification_probabilities: list[dict] = Field(default_factory=list)
    # Plan shape fields surfaced for the UI
    question_type: str = "alpha_finding"
    benchmark: str = ""
    instrument_preference: str = "stock"
    idea_archetype: list[str] = Field(default_factory=list)
    sub_questions: list[str] = Field(default_factory=list)
    falsification_criteria: list[str] = Field(default_factory=list)
    regime_sensitivity: list[dict] = Field(default_factory=list)
    macro_context: dict = Field(default_factory=dict)

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
