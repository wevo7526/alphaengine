"""
infra/user_context.py — Single source of truth for per-user runtime context.

Every place in the system that previously hardcoded a $100k portfolio base
or ignored mandate/benchmark/role now resolves through these helpers. The
intent: when a user types "$10M" into onboarding or Settings, every dollar
figure in risk math, stress, position sizing, and agent reasoning reflects
THAT user's actual book — not a retail-default placeholder.

Two layers:

  1. `resolve_portfolio_base(user_id)` — the dollar basis used for any
     percentage → dollar conversion (risk dashboard, stress P&L, optimizer
     trade sizes). Returns the user's `portfolio_size_usd`, falling back
     to 100_000 only when no profile exists or the value is unset.

  2. `resolve_user_context(user_id)` — the full structured context block
     that gets passed into the agent pipeline. Captures role, mandate,
     benchmark, and portfolio_base together so prompts can be conditioned
     on the kind of book the user actually runs.

Both helpers are failure-safe — any DB error falls back to platform
defaults rather than blocking trade math or analysis. The cost of a
default-on-failure (slight mismatch in dollar figures) is far lower than
crashing the request.
"""

from __future__ import annotations

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


# Platform default — what we used to hardcode everywhere. Kept as a single
# named constant so it's explicit when a path is falling back vs. honoring
# the user's actual size.
DEFAULT_PORTFOLIO_BASE_USD = 100_000.0

# Mandate enum — mirrors the values stored in user_profiles.mandate and
# the choices offered in the onboarding wizard / Settings page. Any new
# mandate added here must also be added to the Strategist's prompt and
# the mandate validator in agents/mandate_gate.py.
VALID_MANDATES = frozenset({
    "long_only", "long_short", "market_neutral", "macro", "multi_strat",
})
DEFAULT_MANDATE = "long_short"

# Benchmark enum — must match the buttons on Settings. SPY chosen as
# fallback because every quant module already defaults to SPY today.
VALID_BENCHMARKS = frozenset({"SPY", "QQQ", "IWM", "ACWI"})
DEFAULT_BENCHMARK = "SPY"

VALID_ROLES = frozenset({"pm", "analyst", "allocator", "other"})


class UserContext(TypedDict):
    """Structured runtime context passed into the agent pipeline.

    `portfolio_base_usd` is the resolved dollar basis (never None). All
    other fields fall back to their platform defaults when the user has
    no profile or has left the field unset.
    """
    user_id: str | None
    full_name: str | None
    role: str
    portfolio_base_usd: float
    benchmark: str
    mandate: str


def _default_context(user_id: str | None) -> UserContext:
    return UserContext(
        user_id=user_id,
        full_name=None,
        role="other",
        portfolio_base_usd=DEFAULT_PORTFOLIO_BASE_USD,
        benchmark=DEFAULT_BENCHMARK,
        mandate=DEFAULT_MANDATE,
    )


async def resolve_portfolio_base(user_id: str | None) -> float:
    """Resolve the dollar basis for a user. Failure-safe — defaults on error.

    Use anywhere a percentage needs to be converted to a dollar amount:
    risk dashboards, stress P&L, optimizer trade sizes, backtest initial
    capital, etc. The result reflects the user's actual book size when
    available, the platform default otherwise.
    """
    if not user_id:
        return DEFAULT_PORTFOLIO_BASE_USD
    try:
        from db.repositories import UserProfileRepository
        profile = await UserProfileRepository.get(user_id)
        if not profile:
            return DEFAULT_PORTFOLIO_BASE_USD
        size = profile.get("portfolio_size_usd")
        if size is None or float(size) <= 0:
            return DEFAULT_PORTFOLIO_BASE_USD
        return float(size)
    except Exception as e:
        logger.warning(f"resolve_portfolio_base fallback for {user_id}: {e}")
        return DEFAULT_PORTFOLIO_BASE_USD


async def resolve_user_context(user_id: str | None) -> UserContext:
    """Load the full user_context block for the agent pipeline.

    Always returns a fully-populated UserContext — missing fields fall
    back to platform defaults. Any DB error is logged at WARNING and
    treated as "no profile exists", so a transient database hiccup
    can't break analysis.
    """
    if not user_id:
        return _default_context(user_id)
    try:
        from db.repositories import UserProfileRepository
        profile = await UserProfileRepository.get(user_id)
    except Exception as e:
        logger.warning(f"resolve_user_context fallback for {user_id}: {e}")
        return _default_context(user_id)

    if not profile:
        return _default_context(user_id)

    role = (profile.get("role") or "other").lower()
    if role not in VALID_ROLES:
        role = "other"

    mandate = (profile.get("mandate") or DEFAULT_MANDATE).lower()
    if mandate not in VALID_MANDATES:
        mandate = DEFAULT_MANDATE

    benchmark = (profile.get("benchmark") or DEFAULT_BENCHMARK).upper()
    if benchmark not in VALID_BENCHMARKS:
        benchmark = DEFAULT_BENCHMARK

    raw_size = profile.get("portfolio_size_usd")
    try:
        size = float(raw_size) if raw_size is not None else DEFAULT_PORTFOLIO_BASE_USD
        if size <= 0:
            size = DEFAULT_PORTFOLIO_BASE_USD
    except (TypeError, ValueError):
        size = DEFAULT_PORTFOLIO_BASE_USD

    return UserContext(
        user_id=user_id,
        full_name=profile.get("full_name"),
        role=role,
        portfolio_base_usd=size,
        benchmark=benchmark,
        mandate=mandate,
    )


def format_usd(amount: float) -> str:
    """Compact USD formatter used by agent prompts.

    Produces "$10.0M" / "$250K" / "$1.5B" style strings — short enough
    to interpolate into a system prompt without bloating it.
    """
    a = abs(amount)
    sign = "-" if amount < 0 else ""
    if a >= 1_000_000_000:
        return f"{sign}${a / 1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.{0 if a >= 10_000_000 else 1}f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.0f}K"
    return f"{sign}${a:.0f}"


# ─── Prompt-block formatters ────────────────────────────────────────────
# Used by every agent that wants to condition its reasoning on the
# resolved user_context. Centralizing the block shape here keeps every
# agent on a consistent contract: same field names, same casing, same
# guidance lines. When we add a new field to UserContext, only this one
# function needs updating.

_MANDATE_GUIDANCE = {
    "long_only":      "Only outright long positions. NEVER propose shorts, puts, or net-short structures. If the thesis is bearish, recommend reducing exposure or selecting a defensive long.",
    "long_short":     "Both directions allowed. Pair trades and L/S spreads are first-class structures.",
    "market_neutral": "Maintain dollar/beta neutrality. EVERY long must have a corresponding short or hedge. Net beta target ~0.",
    "macro":          "Cross-asset themes preferred. Favor index ETFs, futures proxies, sector rotations, and rates/credit/FX instruments over single-name equity bets.",
    "multi_strat":    "All structures allowed — diversify across style labels (growth / value / quality / momentum / event-driven / etc.).",
}

_ROLE_GUIDANCE = {
    "pm":        "Audience is a PM making allocation decisions today. Frame for decision velocity: lead with action, then evidence.",
    "analyst":   "Audience is an analyst building the model. Be detailed on data, ratios, and methodology — they want the work to verify themselves.",
    "allocator": "Audience is an allocator thinking in portfolio construction terms. Emphasize fit with mandate, factor exposure, and how the idea sits next to the existing book.",
    "other":     "Audience is a sophisticated investor. Balance decision-readiness with analytical depth.",
}


def _format_user_context_block(user_context: dict | None) -> str:
    """Format the resolved user_context as a prompt block.

    Returns an empty string when no context is available so callers can
    safely f-string the result without checking. The block opens with a
    `=== USER CONTEXT ===` heading consistent with other context blocks
    (macro, scorecard, thread) used across the desk.

    When `user_context` carries a `memory` sub-block (watchlist tickers,
    recent themes), it's appended to the same block so the LLM sees the
    user's profile and their actual usage history together.
    """
    if not user_context:
        return ""

    role = (user_context.get("role") or "other").lower()
    mandate = (user_context.get("mandate") or DEFAULT_MANDATE).lower()
    benchmark = (user_context.get("benchmark") or DEFAULT_BENCHMARK).upper()
    full_name = user_context.get("full_name") or "—"
    size_usd = float(user_context.get("portfolio_base_usd") or DEFAULT_PORTFOLIO_BASE_USD)
    size_label = format_usd(size_usd)

    role_label = role.upper()
    mandate_label = mandate.replace("_", " ").title()
    mandate_rule = _MANDATE_GUIDANCE.get(mandate, _MANDATE_GUIDANCE[DEFAULT_MANDATE])
    role_rule = _ROLE_GUIDANCE.get(role, _ROLE_GUIDANCE["other"])

    block = (
        "\n\n=== USER CONTEXT ===\n"
        f"Name: {full_name}\n"
        f"Role: {role_label}\n"
        f"Book size: {size_label} (use this to express position sizes in real dollars where it helps)\n"
        f"Mandate: {mandate_label} — {mandate_rule}\n"
        f"Benchmark: {benchmark} (anchor relative-performance and beta language to this index)\n"
        f"Audience guidance: {role_rule}\n"
    )

    # Optional memory sub-block — surfaces the user's actual usage history
    # (watchlist tickers, themes they keep returning to) so agents can
    # weight discovery toward names the user is already tracking.
    memory = user_context.get("memory") or {}
    watchlist = memory.get("watchlist") or []
    recent_themes = memory.get("recent_themes") or []
    recent_tickers = memory.get("recent_tickers") or []
    if watchlist or recent_themes or recent_tickers:
        block += "Recent usage:\n"
        if watchlist:
            block += f"  - Watchlist: {', '.join(watchlist[:15])}\n"
        if recent_tickers:
            block += f"  - Recently analyzed: {', '.join(recent_tickers[:15])}\n"
        if recent_themes:
            block += f"  - Recurring themes: {', '.join(recent_themes[:10])}\n"
        block += (
            "  When the user's query touches these names or themes, bias screening "
            "and idea generation toward them. They've already done the work — "
            "don't surface a fresh universe scan when the user is asking about "
            "names they're already tracking.\n"
        )

    return block


async def resolve_user_memory(
    user_id: str | None,
    *,
    memo_limit: int = 10,
    watchlist_limit: int = 20,
) -> dict:
    """Build the per-user memory block from DB activity. Failure-safe.

    Returns a dict shape: {watchlist, recent_tickers, recent_themes}. Empty
    lists on any failure — the agent pipeline must work for cold-start
    users with no usage history.
    """
    empty = {"watchlist": [], "recent_tickers": [], "recent_themes": []}
    if not user_id:
        return empty
    try:
        from sqlalchemy import select, desc
        from db.database import async_session
        from db.models import WatchlistRecord, IntelligenceMemoRecord
    except Exception as e:
        logger.debug(f"resolve_user_memory imports failed: {e}")
        return empty

    watchlist: list[str] = []
    recent_tickers: list[str] = []
    recent_themes: list[str] = []

    try:
        async with async_session() as session:
            wl = await session.execute(
                select(WatchlistRecord)
                .where(WatchlistRecord.user_id == user_id)
                .order_by(desc(WatchlistRecord.added_at))
                .limit(watchlist_limit)
            )
            watchlist = [r.ticker for r in wl.scalars().all() if r.ticker]

            memos = await session.execute(
                select(IntelligenceMemoRecord)
                .where(IntelligenceMemoRecord.user_id == user_id)
                .order_by(desc(IntelligenceMemoRecord.created_at))
                .limit(memo_limit)
            )
            ticker_set: set[str] = set()
            theme_set: set[str] = set()
            for m in memos.scalars().all():
                for t in (m.tickers_analyzed or []):
                    if isinstance(t, str):
                        ticker_set.add(t.upper())
                for th in (m.themes or []):
                    if isinstance(th, str):
                        theme_set.add(th)
            recent_tickers = sorted(ticker_set)
            recent_themes = sorted(theme_set)
    except Exception as e:
        logger.debug(f"resolve_user_memory query failed: {e}")
        return empty

    return {
        "watchlist": watchlist,
        "recent_tickers": recent_tickers,
        "recent_themes": recent_themes,
    }
