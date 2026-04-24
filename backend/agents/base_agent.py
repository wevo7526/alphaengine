"""
Base agent class for the hedge fund research desk.

Agents that use tool-calling inherit from BaseAgent.
Pure reasoning agents (Query Interpreter, CIO Synthesizer) use the LLM directly.

Stability notes:
  - The shared ChatAnthropic client is safe to call concurrently; it's an
    HTTP client under the hood.
  - The AgentExecutor is NOT reused across requests: LangChain's executor
    carries callback wiring and per-invocation state. Sharing one across
    coroutines causes interleaved tool histories on concurrent requests.
    Each `analyze()` call builds a fresh executor; tool objects themselves
    are still pooled because tool construction is cheap and stateless.
  - JSON parsing has graceful fallback but now also tries once more with
    a simple repair pass for the most common LLM mistakes before giving up.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from agents.schemas import AgentOutput
from config import settings

logger = logging.getLogger(__name__)

_llm: ChatAnthropic | None = None


def get_llm() -> ChatAnthropic:
    """
    Lazily build the shared ChatAnthropic client.

      - temperature=0 for deterministic financial reasoning
      - max_retries=4 handles 529 overloaded + transient 5xx; Anthropic SDK
        implements exponential backoff automatically
      - timeout=90 so a hung request unwinds well within the pipeline's
        per-agent deadline (120–240s)
    """
    global _llm
    if _llm is None:
        if not settings.ANTHROPIC_API_KEY:
            logger.error(
                "ANTHROPIC_API_KEY is not set — any agent call will fail. "
                "Set this via Railway environment variables."
            )
        _llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=settings.ANTHROPIC_API_KEY,
            max_tokens=4096,
            temperature=0,
            max_retries=4,
            timeout=90,
        )
    return _llm


class BaseAgent:
    """Base class for tool-calling agents."""

    agent_name: str = "base_agent"
    system_prompt: str = "You are a financial analyst."
    output_instructions: str = "Respond with valid JSON."
    max_iterations: int = 6

    def __init__(self):
        self.llm = get_llm()
        # Cache tools once — they're stateless. We DO NOT cache the executor
        # because it carries callback wiring and per-call scratchpad state.
        self._tools: list[BaseTool] | None = None

    def get_tools(self) -> list[BaseTool]:
        raise NotImplementedError

    def build_input_prompt(self, context: dict) -> str:
        raise NotImplementedError

    def _get_cached_tools(self) -> list[BaseTool]:
        if self._tools is None:
            self._tools = self.get_tools()
        return self._tools

    def _build_executor(self, callbacks: list | None = None) -> AgentExecutor:
        """
        Build a fresh executor per call. Sharing executors across concurrent
        requests causes interleaved scratchpad state on the AgentExecutor.
        """
        tools = self._get_cached_tools()
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt + "\n\n" + self.output_instructions),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(self.llm, tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=self.max_iterations,
            handle_parsing_errors=True,
            callbacks=callbacks or None,
        )

    async def analyze(self, context: dict, callbacks: list | None = None) -> AgentOutput:
        """Run analysis given the pipeline context."""
        input_prompt = self.build_input_prompt(context)
        logger.info(f"[{self.agent_name}] Starting analysis")

        try:
            executor = self._build_executor(callbacks=callbacks)
            config = {"callbacks": callbacks} if callbacks else {}
            result = await executor.ainvoke({"input": input_prompt}, config=config)
            output_text = self._extract_text(result.get("output", "{}"))
            parsed = self._parse_json(output_text)
            logger.info(f"[{self.agent_name}] Analysis complete")
            return AgentOutput(
                agent_name=self.agent_name,
                output=parsed,
                reasoning=parsed.get("reasoning", parsed.get("data_summary", "")),
            )
        except Exception as e:
            logger.error(f"[{self.agent_name}] Analysis failed: {e}")
            return AgentOutput(
                agent_name=self.agent_name,
                output={},
                error=str(e),
            )

    def _extract_text(self, output: Any) -> str:
        """Extract a plain text string from whatever LangChain returns."""
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            parts = []
            for item in output:
                if isinstance(item, dict):
                    parts.append(item.get("text", item.get("content", str(item))))
                elif isinstance(item, str):
                    parts.append(item)
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        if isinstance(output, dict):
            return output.get("text", output.get("content", json.dumps(output)))
        return str(output)

    def _parse_json(self, text: str) -> dict:
        """Extract JSON from LLM output, with progressive repair passes."""
        if not text or not text.strip():
            raise ValueError("Empty output from agent")

        text = text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        # 1. Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Extract outermost {}; handles prose prefixes like "Here is the analysis:"
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            candidate = text[start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 3. Common LLM mistakes: trailing commas, Python-style True/False
                repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                repaired = re.sub(r"\bTrue\b", "true", repaired)
                repaired = re.sub(r"\bFalse\b", "false", repaired)
                repaired = re.sub(r"\bNone\b", "null", repaired)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

        # Last resort: surface text verbatim with a parse_error flag so callers
        # can detect and degrade explicitly instead of silently losing data.
        logger.warning(f"[{self.agent_name}] Could not parse JSON, wrapping as text")
        return {"data_summary": text[:2000], "parse_error": True}
