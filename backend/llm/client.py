"""
Tiered ChatAnthropic factory + prompt-cache helpers.

One cached client per (tier) so we don't rebuild HTTP clients per call. The
clients share the proven parameters from the original base_agent.get_llm
(temperature=0, max_tokens=4096, max_retries=4, timeout=90).
"""

from __future__ import annotations

import logging

from langchain_anthropic import ChatAnthropic

from config import settings

logger = logging.getLogger(__name__)

# tier name → settings attribute holding the model id
_TIER_SETTING = {
    "extraction": "LLM_MODEL_EXTRACTION",
    "synthesis": "LLM_MODEL_SYNTHESIS",
    "heavy": "LLM_MODEL_HEAVY",
}

# Per-tier defaults. Extraction work is short and structured, so it gets a
# tighter token budget; synthesis/heavy keep the original 4096.
_TIER_MAX_TOKENS = {
    "extraction": 2048,
    "synthesis": 4096,
    "heavy": 4096,
}

_clients: dict[str, ChatAnthropic] = {}


def resolve_model(tier: str) -> str:
    """Map a tier name to its configured model id (defaults to synthesis)."""
    setting = _TIER_SETTING.get(tier, "LLM_MODEL_SYNTHESIS")
    return getattr(settings, setting)


def get_llm(tier: str = "synthesis") -> ChatAnthropic:
    """Return a cached ChatAnthropic for the given tier.

    tier ∈ {"extraction", "synthesis", "heavy"}; unknown tiers fall back to
    synthesis so a typo degrades to "correct but pricier" rather than crashing.
    """
    if tier not in _TIER_SETTING:
        logger.warning("[llm] unknown tier %r — falling back to synthesis", tier)
        tier = "synthesis"
    client = _clients.get(tier)
    if client is None:
        if not settings.ANTHROPIC_API_KEY:
            logger.error(
                "ANTHROPIC_API_KEY is not set — any LLM call will fail. "
                "Set this via Railway environment variables."
            )
        model = resolve_model(tier)
        client = ChatAnthropic(
            model=model,
            api_key=settings.ANTHROPIC_API_KEY,
            max_tokens=_TIER_MAX_TOKENS.get(tier, 4096),
            temperature=0,
            max_retries=4,
            timeout=90,
        )
        _clients[tier] = client
        logger.info("[llm] tier=%s → model=%s", tier, model)
    return client


def cache_system_block(text: str) -> str | list[dict]:
    """Wrap a static system prompt for Anthropic prompt caching.

    Returns a single ephemeral-cached content block when caching is enabled,
    else the plain string. langchain-anthropic passes `cache_control` through
    to the API; if a future SDK ignores it, the call still succeeds (the
    marker is simply not honored), so this is safe to apply unconditionally.

    Use for the large, static portion of a system prompt (the analytical
    framework / extraction schema) that is identical across per-name calls.
    """
    if not settings.LLM_PROMPT_CACHE or not text:
        return text
    return [{
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }]
