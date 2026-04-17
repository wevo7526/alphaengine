"""
Desk stream callbacks — push live agent activity events into an asyncio queue
so the streaming endpoint can yield them as SSE events to the frontend.

This is what turns the 5-dot spinner into a real-time activity feed:
- Tool calls appear as they happen
- Tool results are summarized to ~100 chars per event
- Agent actions and errors surface to the UI

The callback never blocks the agent — events are dropped on the queue
asynchronously and the agent continues its work.
"""

import asyncio
import logging
import time
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)


def _summarize_tool_args(tool_name: str, tool_input: Any) -> str:
    """Extract a short, user-readable summary of tool arguments."""
    if isinstance(tool_input, dict):
        # Most common: {ticker: "NVDA"} or {query: "..."} or {period: "3mo"}
        if "ticker" in tool_input:
            return str(tool_input["ticker"])
        if "query" in tool_input:
            q = str(tool_input["query"])
            return q[:60] + "..." if len(q) > 60 else q
        if "query_text" in tool_input:
            q = str(tool_input["query_text"])
            return q[:60] + "..." if len(q) > 60 else q
        # Fallback: join key=val pairs
        parts = [f"{k}={v}" for k, v in list(tool_input.items())[:3]]
        return ", ".join(parts)[:80]
    if isinstance(tool_input, str):
        return tool_input[:80]
    return str(tool_input)[:80]


def _summarize_tool_result(tool_name: str, output: Any) -> str:
    """
    Extract a short, user-readable summary of tool output.
    Each tool has a custom summarizer that pulls the key facts.
    """
    try:
        if tool_name == "get_macro_snapshot":
            if isinstance(output, dict):
                count = len(output)
                vix = output.get("vix", {}).get("value")
                ff = output.get("fed_funds_rate", {}).get("value")
                parts = [f"{count}/13 indicators"]
                if vix is not None:
                    parts.append(f"VIX {vix:.2f}")
                if ff is not None:
                    parts.append(f"FFR {ff:.2f}%")
                return ", ".join(parts)

        if tool_name == "get_fundamentals":
            if isinstance(output, dict):
                parts = []
                if output.get("pe_ratio") is not None:
                    parts.append(f"P/E {output['pe_ratio']:.1f}x")
                if output.get("revenue_growth") is not None:
                    parts.append(f"Rev {output['revenue_growth'] * 100:+.1f}%")
                if output.get("profit_margin") is not None:
                    parts.append(f"Margin {output['profit_margin'] * 100:.1f}%")
                if output.get("beta") is not None:
                    parts.append(f"β {output['beta']:.2f}")
                if parts:
                    return ", ".join(parts)

        if tool_name == "get_price_history":
            if isinstance(output, list) and output:
                first = output[0].get("close") if isinstance(output[0], dict) else None
                last = output[-1].get("close") if isinstance(output[-1], dict) else None
                if first and last:
                    chg = (last - first) / first * 100
                    return f"{len(output)} bars, {chg:+.2f}% over range"
                return f"{len(output)} bars"

        if tool_name == "get_options_chain":
            if isinstance(output, dict):
                calls = len(output.get("calls", []))
                puts = len(output.get("puts", []))
                return f"{calls} calls, {puts} puts"

        if tool_name in ("get_ticker_news", "get_market_news"):
            if isinstance(output, list):
                if output:
                    top = output[0].get("title", "") if isinstance(output[0], dict) else ""
                    top = top[:60] + "..." if len(top) > 60 else top
                    return f"{len(output)} articles: {top}"
                return "0 articles"

        if tool_name == "get_finnhub_news":
            if isinstance(output, dict):
                count = output.get("article_count", 0)
                return f"{count} Finnhub articles"

        if tool_name == "score_news_sentiment":
            if isinstance(output, dict):
                compound = output.get("compound")
                label = output.get("label", "")
                if compound is not None:
                    return f"{label} ({compound:+.2f})"

        if tool_name == "get_options_analysis":
            if isinstance(output, dict):
                parts = []
                if output.get("put_call_ratio") is not None:
                    parts.append(f"P/C {output['put_call_ratio']:.2f}")
                if output.get("atm_iv") is not None:
                    parts.append(f"IV {output['atm_iv'] * 100:.1f}%")
                if output.get("implied_move_pct") is not None:
                    parts.append(f"move {output['implied_move_pct']:.1f}%")
                if parts:
                    return ", ".join(parts)

        if tool_name in ("get_recent_filings", "search_filings_fulltext"):
            if isinstance(output, dict):
                filings = output.get("filings", [])
                return f"{len(filings)} filings"

        if tool_name == "get_insider_trades":
            if isinstance(output, dict):
                data = output.get("data", [])
                return f"{len(data)} insider transactions"

        if tool_name.endswith("_history"):
            if isinstance(output, list):
                return f"{len(output)} observations"

        if tool_name == "get_current_price":
            if isinstance(output, dict):
                price = output.get("current_price")
                if price is not None:
                    return f"${price:.2f}"

        if tool_name == "get_recent_prices":
            if isinstance(output, list):
                return f"{len(output)} bars"

        if tool_name == "search_web":
            if isinstance(output, list):
                return f"{len(output)} web results"

        # Generic fallback
        if isinstance(output, dict):
            return f"{len(output)} fields"
        if isinstance(output, list):
            return f"{len(output)} items"
        s = str(output)
        return s[:80] + "..." if len(s) > 80 else s
    except Exception as e:
        logger.debug(f"Tool result summary failed for {tool_name}: {e}")
        return "completed"


class DeskStreamCallback(AsyncCallbackHandler):
    """
    Pushes live agent activity into an asyncio queue for SSE streaming.

    Constructor:
        queue: asyncio.Queue where events are pushed
        desk: desk name ("research", "risk", "portfolio", "cio", "screening")
        agent: agent name within the desk (optional)
    """

    def __init__(self, queue: asyncio.Queue, desk: str, agent: str | None = None):
        super().__init__()
        self.queue = queue
        self.desk = desk
        self.agent = agent or desk
        self._tool_starts: dict[str, float] = {}

    async def _push(self, event: dict):
        """Push an event, dropping silently if queue is full (never block agent)."""
        try:
            # Never await — put_nowait so agent never waits on frontend
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug(f"Event queue full, dropping {event.get('type')}")
        except Exception as e:
            logger.debug(f"Callback push failed: {e}")

    async def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        tool_name = serialized.get("name", "unknown") if serialized else "unknown"
        # input_str is a string representation of the tool call
        args_summary = str(input_str)[:80] if input_str else ""
        # Try to parse tool input from kwargs
        try:
            tool_input = kwargs.get("inputs", {}) or kwargs.get("tool_input", {})
            if tool_input:
                args_summary = _summarize_tool_args(tool_name, tool_input)
        except Exception:
            pass

        self._tool_starts[str(run_id)] = time.time()
        await self._push({
            "type": "tool_call",
            "desk": self.desk,
            "agent": self.agent,
            "tool": tool_name,
            "args_summary": args_summary,
            "timestamp": time.time(),
        })

    async def on_tool_end(self, output, *, run_id, **kwargs):
        tool_name = kwargs.get("name", "unknown")
        if tool_name == "unknown":
            # Try other common keys
            serialized = kwargs.get("serialized") or {}
            if isinstance(serialized, dict):
                tool_name = serialized.get("name", "unknown")

        start = self._tool_starts.pop(str(run_id), None)
        duration_ms = int((time.time() - start) * 1000) if start else None

        result_summary = _summarize_tool_result(tool_name, output)

        await self._push({
            "type": "tool_result",
            "desk": self.desk,
            "agent": self.agent,
            "tool": tool_name,
            "result_summary": result_summary,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })

    async def on_tool_error(self, error, *, run_id, **kwargs):
        tool_name = kwargs.get("name", "unknown")
        await self._push({
            "type": "tool_error",
            "desk": self.desk,
            "agent": self.agent,
            "tool": tool_name,
            "error": str(error)[:200],
            "timestamp": time.time(),
        })

    async def on_agent_action(self, action, *, run_id, **kwargs):
        # Fired when the agent decides to call a tool.
        # on_tool_start covers this, so we don't duplicate. Left in place for future use.
        pass

    async def on_agent_finish(self, finish, *, run_id, **kwargs):
        # Fired when the agent produces its final answer.
        pass
