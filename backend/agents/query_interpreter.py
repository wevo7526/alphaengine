"""
Query Interpreter — first agent in the pipeline.

Parses the user's freeform query and produces an AnalysisPlan.
Pure LLM reasoning — no tool calling, no data fetching.
This is the fastest agent (~2-3 seconds).
"""

from langchain_core.messages import SystemMessage, HumanMessage
import json
import logging

from agents.base_agent import get_llm
from agents.schemas import AnalysisPlan, AgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Chief Investment Officer's assistant at a quantitative hedge fund.
Your job is to interpret research queries and create structured analysis plans.

Given a user query, produce a JSON object with this exact schema:
{
    "query": "<original query>",
    "intent": "ticker_analysis | thematic_research | risk_assessment | portfolio_ideas | market_regime",
    "tickers": ["<ticker1>", "<ticker2>"],
    "sectors": ["<sector1>"],
    "themes": ["<theme1>", "<theme2>"],
    "data_requests": ["<specific instruction for Research Analyst>", ...],
    "risk_focus": ["<risk dimension>", ...],
    "time_horizon": "intraday | days | weeks | months"
}

Classification rules:

For ticker_analysis (e.g., "Analyze AAPL", "Is NVDA overvalued?"):
  - The ticker is explicit. Include it in tickers[].
  - data_requests: fundamentals, price history, recent news, key filings, technicals.
  - Default time_horizon: weeks.

For thematic_research (e.g., "find alpha given geopolitical trends", "AI infrastructure plays"):
  - Infer 3-8 relevant tickers that benefit or suffer from the theme.
  - data_requests: macro snapshot, sector news, fundamentals for inferred tickers.
  - Include broad themes in themes[].

For risk_assessment (e.g., "what are the biggest risks right now?"):
  - Focus on macro data: yield curve, credit spreads, VIX, fed funds.
  - risk_focus: list specific risk categories (macro, credit, geopolitical, etc.).
  - tickers: include benchmark ETFs (SPY, TLT, GLD, VIX).

For portfolio_ideas (e.g., "give me 5 trade ideas for a risk-on environment"):
  - Infer 8-12 tickers across sectors based on the stated environment.
  - data_requests: macro snapshot + fundamentals + news for each.

For market_regime (e.g., "what's the macro outlook?"):
  - Focus on macro indicators. Minimal ticker-specific data.
  - tickers: benchmark ETFs (SPY, TLT, GLD, DXY).
  - data_requests: macro snapshot, yield curve history, credit spread history, VIX history.

Be specific in data_requests — these are instructions the Research Analyst will execute.
For example: "Pull fundamentals for AAPL", "Get macro snapshot", "Search news for tariff impact on semiconductors".

Keep tickers to 8 max to conserve API limits. Be selective — quality over quantity."""


class QueryInterpreter:
    agent_name = "query_interpreter"

    def __init__(self):
        self.llm = get_llm()

    async def interpret(self, query: str, callbacks: list | None = None) -> AnalysisPlan:
        """Parse a freeform query into a structured AnalysisPlan."""
        logger.info(f"[query_interpreter] Interpreting: {query}")

        config = {"callbacks": callbacks} if callbacks else {}
        result = await self.llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Query: {query}\n\nProduce the analysis plan as JSON."),
        ], config=config)

        text = result.content.strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
            else:
                raise ValueError(f"Could not parse plan JSON: {text[:200]}")

        plan = AnalysisPlan(**data)
        logger.info(
            f"[query_interpreter] Plan: intent={plan.intent.value}, "
            f"tickers={plan.tickers}, themes={plan.themes}, "
            f"{len(plan.data_requests)} data requests"
        )
        return plan
