"""
LLM client layer — model tiering + prompt caching (Cost Discipline).

Single place that decides which Claude model serves a given workload and how
static context is cached:

  - tier="extraction" → cheap model (Haiku) for bulk filing/transcript
    classification across the universe (Build Plan Phase 2 load).
  - tier="synthesis"  → reasoning model (Sonnet) for final memo synthesis.
    Default tier; matches the historically-pinned model so existing agent
    behavior is unchanged.
  - tier="heavy"      → Opus, reserved for cases reasoning quality justifies
    the cost. Not used by default — "don't synthesize memos on Opus."

`cache_system_block` wraps a large static system prompt with Anthropic's
ephemeral prompt-cache marker so every per-name call reads the cache (~10% of
input cost) instead of re-billing the full prompt.
"""

from llm.client import get_llm, cache_system_block, resolve_model

__all__ = ["get_llm", "cache_system_block", "resolve_model"]
