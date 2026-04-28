export type SignalDirection =
  | "strong_bullish"
  | "bullish"
  | "neutral"
  | "bearish"
  | "strong_bearish";

export type QueryIntent =
  | "ticker_analysis"
  | "thematic_research"
  | "risk_assessment"
  | "portfolio_ideas"
  | "market_regime";

export interface RiskFactor {
  category: string;
  description: string;
  severity: string;
  probability: string;
  mitigation: string;
}

export interface TradeIdea {
  ticker: string;
  direction: SignalDirection;
  conviction: number;
  thesis: string;
  entry_zone: string | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward_ratio: number | null;
  position_size_pct: number;
  time_horizon: string;
  catalysts: string[];
  risks: string[];
  // Set when the server-side validator overrode the LLM's entry/stop/target
  // to anchor against live price. Surfaced as a small badge on the trade card.
  price_corrected?: boolean;
  live_price_used?: number;
  original_entry_zone?: string | null;
  // Beta layering / structural decomposition
  beta_to_spy?: number | null;
  sector?: string | null;
  regime_conditional_size_pct?: number | null;
  structure_type?: string | null;
  pair_short_leg?: string | null;
}

export interface IntelligenceMemo {
  id?: string;
  query: string;
  timestamp: string;
  title: string;
  executive_summary: string;
  analysis: string;
  key_findings: string[];
  macro_regime: string;
  overall_risk_level: string;
  risk_factors: RiskFactor[];
  trade_ideas: TradeIdea[];
  portfolio_positioning: string;
  hedging_recommendations: string[];
  tickers_analyzed: string[];
  themes: string[];
  intent: QueryIntent;
  created_at?: string;
  // Desk 5B Decision Gate
  decision?: "GO" | "NO-GO" | "WATCH";
  decision_reason?: string;
  decision_confidence?: number;
  // Quality / provenance signals
  grounding?: {
    confidence?: "high" | "medium" | "low" | "n/a";
    numeric_claims?: number;
    ungrounded_count?: number;
    desk_count?: number;
  };
  plan_confidence?: number;
  plan_confidence_reason?: string;
  // Phase-2 plan-shape signals surfaced for the UI
  data_quality?: "complete" | "degraded" | "critical";
  question_type?: string;
  benchmark?: string;
  instrument_preference?: string;
  idea_archetype?: string[];
  sub_questions?: string[];
  sub_question_coverage?: { question: string; answered: boolean }[];
  sub_question_answered_pct?: number;
  falsification_criteria?: string[];
  falsification_probabilities?: { criterion: string; probability: string; reasoning?: string }[];
  diversity?: {
    monolithic?: boolean;
    reason?: string;
    direction_split?: { long?: number; short?: number; neutral?: number };
    sector_concentration_pct?: number;
    top_sector?: string;
  };
  regime_sensitivity?: {
    regime: string;
    ideal_position?: string;
    conviction_multiplier?: number;
    key_assumption?: string;
  }[];
  macro_context?: {
    current_regime?: string;
    confidence?: number;
    vix?: number | null;
    credit_spreads?: number | null;
    yield_curve?: number | null;
    fed_funds_rate?: number | null;
  };
}

export interface MacroIndicator {
  value: number;
  previous: number;
  change: number;
  date: string;
  series_id: string;
}

export interface NewsArticle {
  title: string;
  description: string;
  source: string;
  published_at: string;
  url: string;
}

// Computed enrichment data
export interface VolatilityMetrics {
  ticker: string;
  realized_vol_annualized: number;
  annualized_return: number;
  sharpe_ratio: number;
  skewness: number;
  var_95_daily: number;
  max_daily_loss: number;
  max_daily_gain: number;
  observations: number;
}

export interface DrawdownData {
  ticker: string;
  series: { date: string; drawdown: number }[];
  max_drawdown: number;
  current_drawdown: number;
}

export interface SentimentAggregate {
  compound: number;
  label: string;
  count: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  bullish_pct: number;
  bearish_pct: number;
}

export interface TickerAnalytics {
  volatility: VolatilityMetrics;
  drawdown: DrawdownData;
  sparkline: { date: string; close: number }[];
  options?: Record<string, unknown> | null;
  sentiment?: SentimentAggregate | null;
  error?: string;
}

export interface EnrichmentData {
  tickers: string[];
  analytics: Record<string, TickerAnalytics>;
  correlation: { tickers: string[]; matrix: number[][] } | null;
}

export const AGENT_META: Record<
  string,
  { label: string; role: string }
> = {
  query_interpreter: {
    label: "Query Interpreter",
    role: "Parsing query and creating research plan",
  },
  research_analyst: {
    label: "Research Analyst",
    role: "Gathering data from macro, market, news, filings, and technicals",
  },
  risk_manager: {
    label: "Risk Manager",
    role: "Evaluating macro regime, position risks, and tail risks",
  },
  portfolio_strategist: {
    label: "Portfolio Strategist",
    role: "Building actionable trade ideas with entry/exit levels",
  },
  cio_synthesizer: {
    label: "CIO Synthesizer",
    role: "Writing the final intelligence memo",
  },
};

export const DIRECTION_STYLE: Record<
  SignalDirection,
  { label: string; color: string }
> = {
  strong_bullish: { label: "Strong Bullish", color: "text-signal-green" },
  bullish: { label: "Bullish", color: "text-signal-green" },
  neutral: { label: "Neutral", color: "text-text-tertiary" },
  bearish: { label: "Bearish", color: "text-signal-red" },
  strong_bearish: { label: "Strong Bearish", color: "text-signal-red" },
};

export const RISK_LEVEL_STYLE: Record<string, string> = {
  low: "text-signal-green",
  moderate: "text-signal-yellow",
  elevated: "text-signal-yellow",
  high: "text-signal-red",
  extreme: "text-signal-red",
};
