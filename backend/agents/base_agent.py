"""
Base agent class for the hedge fund research desk.

Agents that use tool-calling inherit from BaseAgent.
Pure reasoning agents (Query Interpreter, CIO Synthesizer) use the LLM directly.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from datetime import datetime
import json
import logging

from config import settings
from agents.schemas import AgentOutput

logger = logging.getLogger(__name__)

_llm = None


def get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=settings.ANTHROPIC_API_KEY,
            max_tokens=4096,
            temperature=0,
        )
    return _llm


class BaseAgent:
    """
    Base class for tool-calling agents (Research Analyst, Risk Manager, Portfolio Strategist).

    Subclasses implement:
      - agent_name: str
      - system_prompt: str
      - output_instructions: str  (JSON schema for this agent's output)
      - get_tools() -> list[BaseTool]
      - build_input_prompt(context: dict) -> str
    """

    agent_name: str = "base_agent"
    system_prompt: str = "You are a financial analyst."
    output_instructions: str = "Respond with valid JSON."

    def __init__(self):
        self.llm = get_llm()
        self._executor = None

    def get_tools(self) -> list[BaseTool]:
        raise NotImplementedError

    def build_input_prompt(self, context: dict) -> str:
        raise NotImplementedError

    def _build_executor(self) -> AgentExecutor:
        tools = self.get_tools()
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
            max_iterations=2,
            handle_parsing_errors=True,
        )

    def _get_executor(self) -> AgentExecutor:
        if self._executor is None:
            self._executor = self._build_executor()
        return self._executor

    async def analyze(self, context: dict) -> AgentOutput:
        """Run analysis given the pipeline context."""
        executor = self._get_executor()
        input_prompt = self.build_input_prompt(context)

        logger.info(f"[{self.agent_name}] Starting analysis")

        try:
            result = await executor.ainvoke({"input": input_prompt})
            output_text = result.get("output", "{}")
            # LangChain may return list of content blocks, dicts, or a plain string
            output_text = self._extract_text(output_text)
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

    def _extract_text(self, output) -> str:
        """Extract a plain text string from whatever LangChain returns."""
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            # List of content blocks: [{'text': '...'}, ...] or [string, ...]
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
        """Extract JSON from LLM output, handling markdown fences, mixed text, and edge cases."""
        if not text or not text.strip():
            raise ValueError("Empty output from agent")

        text = text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        # Direct parse attempt
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find the outermost JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            candidate = text[start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Try fixing common LLM JSON issues: trailing commas, single quotes
                import re
                fixed = re.sub(r',\s*([}\]])', r'\1', candidate)  # trailing commas
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        # Last resort: return the text as a summary
        logger.warning(f"[{self.agent_name}] Could not parse JSON, wrapping as text")
        return {"data_summary": text[:2000], "parse_error": True}
