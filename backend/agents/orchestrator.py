"""
Research Desk Orchestrator — LangGraph pipeline for the hedge fund intelligence desk.

Pipeline: Query Interpreter → Research Analyst → Risk Manager → Portfolio Strategist → CIO Synthesizer

Each node receives the full accumulated state from prior agents.
Sequential execution for debuggability and rate-limit friendliness.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END
import asyncio
import logging

from agents.schemas import (
    AnalysisPlan,
    ResearchData,
    RiskAssessment,
    PortfolioStrategy,
    IntelligenceMemo,
    AgentOutput,
)
from agents.query_interpreter import QueryInterpreter
from agents.research_analyst import ResearchAnalyst
from agents.risk_manager import RiskManager
from agents.portfolio_strategist import PortfolioStrategist
from agents.cio_synthesizer import CIOSynthesizer

logger = logging.getLogger(__name__)

# Singleton agent instances — caches persist across requests
_query_interpreter = QueryInterpreter()
_research_analyst = ResearchAnalyst()
_risk_manager = RiskManager()
_portfolio_strategist = PortfolioStrategist()
_cio_synthesizer = CIOSynthesizer()


class ResearchDeskState(TypedDict):
    query: str
    user_id: str | None
    plan_data: dict | None
    research_data: dict | None
    risk_data: dict | None
    strategy_data: dict | None
    scorecard_data: dict | None
    portfolio_data: dict | None
    memo_data: dict | None
    macro_context: dict | None
    # Phase 1 — live prices prefetched in run_strategy, consumed by the
    # compute stage (Fact Sheet) in run_synthesizer.
    live_prices: dict | None
    # Phase 2 — NLP signal bundle (filing change, call tone, 8-K novelty):
    # receipts to thread into the Fact Sheet + coverage/tilt to surface.
    nlp_bundle: dict | None
    data_quality: str | None
    error: str | None
    current_phase: str
    # Phase D — accumulated intermediate_steps per agent for the provenance
    # block. Not serialized over the API; stripped before client return.
    tool_steps_by_agent: dict | None
    # Phase E — conversational thread context (from prior memos when the
    # request specifies parent_memo_id). Drives Interpreter classification
    # and downstream agent context. Empty dict for fresh threads.
    parent_memo_id: str | None
    thread_context: dict | None
    # Phase F — per-user runtime context. Loaded once at pipeline start
    # from infra/user_context.resolve_user_context. Carries portfolio
    # size, role, mandate, and benchmark so every agent reasons against
    # the user's actual book, not a $100k retail placeholder.
    user_context: dict | None


async def _with_timeout(coro, seconds: int, label: str):
    """Wrap an async call with a timeout. Returns None on timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        logger.error(f"[orchestrator] {label} timed out after {seconds}s")
        return None


async def _load_thread_context(parent_memo_id: str | None) -> dict:
    """
    Build a compact context dict from a thread's history. Returned shape:

        {
          "is_followup": bool,
          "thread_id": str | None,
          "parent_memo_id": str | None,
          "sequence": int,                # sequence_in_thread for the NEW memo
          "prior_tickers": [str],         # union across all prior memos
          "prior_themes": [str],
          "prior_decision": str | None,   # most recent GO/NO-GO/WATCH
          "prior_query_class": str | None,
          "prior_titles": [str],          # for display in CIO prompt
          "prior_summary_compressed": str # last memo's exec summary (capped)
        }

    Returns {"is_followup": False, ...zero-valued fields} when no parent
    is given — the orchestrator treats this as a fresh thread. Failures
    (parent_memo_id not found in DB) downgrade to fresh thread silently.
    """
    empty = {
        "is_followup": False,
        "thread_id": None,
        "parent_memo_id": None,
        "sequence": 0,
        "prior_tickers": [],
        "prior_themes": [],
        "prior_decision": None,
        "prior_query_class": None,
        "prior_titles": [],
        "prior_summary_compressed": "",
    }
    if not parent_memo_id:
        return empty

    try:
        from db.repositories import MemoRepository
        thread_id, parent_id, sequence = await MemoRepository.resolve_thread_for_parent(parent_memo_id)
        if not parent_id:
            # Parent was specified but not found — treat as fresh thread
            logger.warning(f"[orchestrator] parent_memo_id={parent_memo_id} not found; starting fresh thread")
            return empty

        chain = await MemoRepository.get_thread(thread_id) if thread_id else []
        if not chain:
            # Thread row exists but get_thread returned empty (shouldn't happen
            # but defensive); use just the parent
            parent = await MemoRepository.get_by_id(parent_id)
            chain = [parent] if parent else []

        all_tickers: set[str] = set()
        all_themes: set[str] = set()
        titles: list[str] = []
        last_decision: str | None = None
        last_qclass: str | None = None
        last_summary = ""
        for m in chain:
            if not m:
                continue
            tickers = m.get("tickers_analyzed") or []
            if isinstance(tickers, list):
                all_tickers.update(t for t in tickers if isinstance(t, str))
            themes = m.get("themes") or []
            if isinstance(themes, list):
                all_themes.update(t for t in themes if isinstance(t, str))
            title = m.get("title")
            if title and isinstance(title, str):
                titles.append(title)
            # The "most recent" loop iteration wins for decision + summary
            last_decision = m.get("decision") or last_decision
            last_qclass = m.get("query_class") or last_qclass
            es = m.get("executive_summary") or ""
            if es:
                last_summary = es

        # Compress prior summary to keep prompt tokens bounded
        compressed = last_summary[:1500] + ("…" if len(last_summary) > 1500 else "")

        return {
            "is_followup": True,
            "thread_id": thread_id,
            "parent_memo_id": parent_id,
            "sequence": int(sequence),
            "prior_tickers": sorted(all_tickers),
            "prior_themes": sorted(all_themes),
            "prior_decision": last_decision,
            "prior_query_class": last_qclass,
            "prior_titles": titles[-5:],
            "prior_summary_compressed": compressed,
        }
    except Exception as e:  # noqa: BLE001 — never let thread load break the run
        logger.warning(f"[orchestrator] _load_thread_context failed: {e}")
        return empty


async def _fetch_macro_context() -> dict:
    """
    Fetch the current macro snapshot + regime classification so the Query
    Interpreter can ground regime_sensitivity from the start. Cached via
    FREDDataClient (1h TTL) so this is cheap on repeated runs.
    """
    try:
        from data.fred_client import FREDDataClient
        from quant.regime import classify_regime
        fred = FREDDataClient()
        snap = fred.get_macro_snapshot() or {}
        vix = snap.get("vix", {}).get("value")
        credit = snap.get("credit_spreads", {}).get("value")
        yc = snap.get("yield_curve_spread", {}).get("value")
        ffr = snap.get("fed_funds_rate", {}).get("value")
        regime_data = classify_regime(vix or 20, credit or 3, yc or 0.5)
        return {
            "current_regime": regime_data.get("current_regime"),
            "confidence": regime_data.get("confidence"),
            "vix": vix,
            "credit_spreads": credit,
            "yield_curve": yc,
            "fed_funds_rate": ffr,
        }
    except Exception as e:
        logger.debug(f"[orchestrator] macro context fetch failed (non-fatal): {e}")
        return {}


async def run_interpreter(state: ResearchDeskState) -> ResearchDeskState:
    state["current_phase"] = "interpreting"
    logger.info(f"[orchestrator] Query Interpreter: {state['query']}")
    try:
        # Pre-fetch macro context + scorecard so the Interpreter sees
        # regime + track record from the start. Both are cheap (cached).
        macro_ctx = await _fetch_macro_context()
        sc = state.get("scorecard_data")
        if sc is None:
            sc = await _fetch_scorecard_for_calibration(state.get("user_id"))
            state["scorecard_data"] = sc

        # Load thread context if this is a follow-up query.
        tc = state.get("thread_context")
        if tc is None:
            tc = await _load_thread_context(state.get("parent_memo_id"))
            state["thread_context"] = tc

        plan = await _with_timeout(
            _query_interpreter.interpret(
                state["query"],
                macro_context=macro_ctx,
                scorecard=sc,
                thread_context=tc,
                user_context=state.get("user_context"),
            ),
            seconds=45, label="Query Interpreter"
        )
        if plan:
            state["plan_data"] = plan.model_dump(mode="json")
            # Stash macro context for downstream desks (Strategist, CIO)
            state["macro_context"] = macro_ctx
        else:
            state["error"] = "Query interpretation timed out"
    except Exception as e:
        logger.error(f"[orchestrator] Query Interpreter failed: {e}")
        state["error"] = f"Failed to interpret query: {e}"
    return state


def _research_completeness_check(plan: dict, research: dict) -> dict:
    """
    Verify the Research Analyst answered each sub_question in data_summary.
    Adds research["sub_question_coverage"] = list of {q, answered} for the
    UI + CIO. Cheap heuristic: looks for 'Q1', 'Q2'... markers OR for
    keyword overlap with the sub-question text.
    """
    sub_qs = (plan or {}).get("sub_questions") or []
    if not sub_qs or not isinstance(research, dict):
        return research
    summary = (research.get("data_summary") or "").lower()
    coverage = []
    for i, q in enumerate(sub_qs, start=1):
        marker = f"q{i}"
        if marker in summary:
            answered = True
        else:
            # keyword fallback — at least 3 of the question's distinguishing
            # words should appear in the summary
            words = [w for w in (q or "").lower().split() if len(w) > 4]
            hits = sum(1 for w in words if w in summary)
            answered = hits >= 3
        coverage.append({"question": q, "answered": bool(answered)})
    research["sub_question_coverage"] = coverage
    answered_count = sum(1 for c in coverage if c["answered"])
    research["sub_question_answered_pct"] = round(answered_count / len(coverage) * 100, 1)
    if answered_count < len(coverage):
        logger.info(
            f"[orchestrator] Research answered {answered_count}/{len(coverage)} sub-questions"
        )
    return research


async def run_research(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "researching"
    logger.info("[orchestrator] Research Analyst gathering data")
    output = await _with_timeout(
        _research_analyst.analyze({
            "plan": state["plan_data"],
            "user_context": state.get("user_context"),
        }),
        seconds=180, label="Research Analyst"
    )
    if output is None:
        state["research_data"] = {"data_summary": "Research timed out — using limited data."}
        state["data_quality"] = "degraded"
    elif output.error:
        logger.warning(f"[orchestrator] Research Analyst error: {output.error}")
        state["research_data"] = {"data_summary": f"Research failed: {output.error}"}
        state["data_quality"] = "critical"
    else:
        state["research_data"] = _research_completeness_check(
            state.get("plan_data") or {}, output.output
        )
    # Accumulate tool calls for the provenance lineage block.
    if output and output.intermediate_steps:
        steps = state.get("tool_steps_by_agent") or {}
        steps["research_analyst"] = list(output.intermediate_steps)
        state["tool_steps_by_agent"] = steps
    return state


async def run_risk(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "risk_assessment"
    logger.info("[orchestrator] Risk Manager evaluating")
    output = await _with_timeout(
        _risk_manager.analyze({
            "plan": state["plan_data"],
            "research": state["research_data"],
            "user_context": state.get("user_context"),
        }),
        seconds=90, label="Risk Manager"
    )
    if output is None or (output and output.error):
        err = output.error if output else "timed out"
        logger.warning(f"[orchestrator] Risk Manager error: {err}")
        state["risk_data"] = {
            "macro_regime": "unknown",
            "regime_confidence": 0,
            "risk_factors": [],
            "overall_risk_level": "elevated",
            "risk_narrative": f"Risk assessment failed: {err}",
        }
    else:
        state["risk_data"] = output.output
    # Accumulate tool calls for the provenance lineage block.
    if output and output.intermediate_steps:
        steps = state.get("tool_steps_by_agent") or {}
        steps["risk_manager"] = list(output.intermediate_steps)
        state["tool_steps_by_agent"] = steps
    return state


async def run_strategy(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "strategizing"
    logger.info("[orchestrator] Portfolio Strategist building trade ideas")

    # Pull portfolio snapshot so Strategist sizes new ideas against the
    # actual book (sector caps, net exposure) rather than in a vacuum.
    if state.get("portfolio_data") is None:
        state["portfolio_data"] = await _fetch_portfolio_snapshot(state.get("user_id"))

    # Pull scorecard early so Strategist can calibrate conviction at the source.
    if state.get("scorecard_data") is None:
        state["scorecard_data"] = await _fetch_scorecard_for_calibration(state.get("user_id"))

    # Pre-fetch CURRENT prices for every plan ticker AND every secondary
    # universe candidate so the Strategist has authoritative data for every
    # potential trade idea source. Prevents LLM from inventing prices and
    # gives mid-cap candidates the same anchoring rigor as mega-caps.
    plan_dict_for_prices = state.get("plan_data") or {}
    plan_tickers = plan_dict_for_prices.get("tickers", []) or []
    secondary = plan_dict_for_prices.get("secondary_universe", []) or []
    # Consider a WIDE field of under-covered names, not just the mega-caps.
    # Prices are cached (1h) so the cost amortizes across queries.
    from config import settings as _uni_settings
    _sec_cap = max(0, int(_uni_settings.STRATEGIST_PRICING_CAP) - len(plan_tickers))
    all_pricing = list(dict.fromkeys(list(plan_tickers) + list(secondary[:_sec_cap])))
    live_prices = await _fetch_live_prices_for(all_pricing)
    # Stash for the Phase 1 compute stage (Fact Sheet) in the synthesizer.
    state["live_prices"] = live_prices

    output = await _with_timeout(
        _portfolio_strategist.analyze({
            "plan": state["plan_data"],
            "research": state["research_data"],
            "risk": state["risk_data"],
            "portfolio": state.get("portfolio_data"),
            "scorecard": state.get("scorecard_data"),
            "live_prices": live_prices,
            "macro_context": state.get("macro_context"),
            "user_context": state.get("user_context"),
        }),
        seconds=90, label="Portfolio Strategist"
    )

    # Post-validate trade ideas against live prices — overrides any LLM
    # hallucinations that snuck past the prompt rules. Also assess diversity
    # against required_style_labels from the plan.
    if output and not output.error and isinstance(output.output, dict):
        from agents.portfolio_strategist import (
            validate_and_fix_trade_ideas,
            assess_diversity,
            validate_tier_compliance,
            classify_tier,
        )
        plan_dict = state.get("plan_data") or {}
        ideas = output.output.get("trade_ideas") or []
        if ideas and live_prices:
            ideas = validate_and_fix_trade_ideas(ideas, live_prices)
            output.output["trade_ideas"] = ideas
        # Backfill tier classification on any idea the LLM didn't tier itself.
        # `classify_tier` is read-only — it inspects screen_source +
        # market_cap_bucket and assigns the discovery tier (1-4 or None).
        for idea in ideas:
            if isinstance(idea, dict) and idea.get("tier") is None:
                t = classify_tier(idea)
                if t is not None:
                    idea["tier"] = t
        # Stash diversity assessment + tier compliance so the UI can flag
        # both monolithic baskets and Tier-1 over-concentration.
        output.output["_diversity"] = assess_diversity(
            ideas, required_style_labels=plan_dict.get("required_style_labels", [])
        )
        output.output["_tier_compliance"] = validate_tier_compliance(ideas)

        # Mandate enforcement — deterministic safety net for the prompt-
        # level guidance the Strategist already received. Long-only books
        # never see shorts; market-neutral books get a net-beta check;
        # macro books get flagged on single-name-heavy slates.
        try:
            from agents.mandate_gate import enforce_mandate
            user_ctx = state.get("user_context") or {}
            mandate = user_ctx.get("mandate")
            ideas_after_gate, mandate_warnings = enforce_mandate(ideas, mandate)
            output.output["trade_ideas"] = ideas_after_gate
            if mandate_warnings:
                output.output["mandate_warnings"] = mandate_warnings
                logger.info(
                    f"[orchestrator] mandate={mandate} produced "
                    f"{len(mandate_warnings)} warning(s); "
                    f"{len(ideas)} → {len(ideas_after_gate)} ideas"
                )
        except Exception as e:
            logger.warning(f"[orchestrator] mandate gate failed (non-fatal): {e}")

        # Phase 2 — NLP signals (filing-change, call-tone, 8-K novelty) tilt
        # conviction DETERMINISTICALLY. No-op unless a filing/transcript flag
        # is enabled (all default off). Receipts are stashed for the Fact Sheet
        # and persistence; the tilt nudges each idea's conviction with a logged
        # adjustment block (the conviction sub-score receipt for Phase 3.4).
        try:
            from config import settings as _nlp_settings
            if _nlp_settings.FILING_NLP_ENABLED or _nlp_settings.TRANSCRIPT_NLP_ENABLED:
                from agents.nlp.runner import gather_nlp_signals, apply_nlp_tilt_to_ideas
                nlp_tickers = (state.get("plan_data") or {}).get("tickers", []) or []
                bundle = await gather_nlp_signals(nlp_tickers)
                ideas2 = output.output.get("trade_ideas") or []
                if ideas2 and bundle["signals"]:
                    ideas2, adj = apply_nlp_tilt_to_ideas(ideas2, bundle["by_ticker_tilt"])
                    output.output["trade_ideas"] = ideas2
                    output.output["nlp_adjustments"] = adj
                state["nlp_bundle"] = {
                    "receipts": bundle.get("receipts", []),
                    "cache_receipts": bundle.get("cache_receipts", []),
                    "coverage": bundle.get("coverage", {}),
                    "by_ticker_tilt": bundle.get("by_ticker_tilt", {}),
                    "signals": [s.model_dump() for s in bundle.get("signals", [])],
                }
                logger.info("[orchestrator] NLP tilt applied: %d signals, coverage=%s",
                            len(bundle.get("signals", [])), bundle.get("coverage", {}).get("covered_pct"))
        except Exception as e:
            logger.warning(f"[orchestrator] NLP signal pass failed (non-fatal): {e}")
    if output is None or (output and output.error):
        err = output.error if output else "timed out"
        logger.warning(f"[orchestrator] Portfolio Strategist error: {err}")
        state["strategy_data"] = {
            "trade_ideas": [],
            "portfolio_positioning": "neutral",
            "hedging_recommendations": [],
            "strategy_narrative": f"Strategy generation failed: {err}",
        }
    else:
        state["strategy_data"] = output.output
    # Accumulate tool calls for the provenance lineage block.
    if output and output.intermediate_steps:
        steps = state.get("tool_steps_by_agent") or {}
        steps["portfolio_strategist"] = list(output.intermediate_steps)
        state["tool_steps_by_agent"] = steps
    return state


async def _fetch_live_prices_for(tickers: list[str]) -> dict[str, float]:
    """
    Pre-fetch current prices for all plan + secondary tickers in ONE call.

    Sources every price from Massive's grouped-daily tape (a single request
    that returns the whole market's daily closes), instead of one fetch per
    ticker. This is the critical rate-budget fix: pricing 50 names costs 1
    Massive call, not 50+. Tickers absent from the tape are simply omitted.
    """
    if not tickers:
        return {}
    from data import price_tape
    from config import settings as _px_settings

    _cap = int(getattr(_px_settings, "STRATEGIST_PRICING_CAP", 50))
    capped = list(dict.fromkeys((t or "").strip().upper() for t in tickers if t))[:_cap]

    try:
        _timeout = float(getattr(_px_settings, "PRICING_TIMEOUT_S", 30.0))
        prices = await asyncio.wait_for(price_tape.aget_tape_prices(capped), timeout=_timeout)
        return {tk: float(px) for tk, px in (prices or {}).items() if px and px > 0}
    except asyncio.TimeoutError:
        logger.warning("[orchestrator] live price prefetch timed out — Strategist runs without LIVE PRICES block")
        return {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[orchestrator] live price prefetch failed: {e}")
        return {}


async def _fetch_prior_memos(
    user_id: str | None,
    tickers: list[str] | None,
    themes: list[str] | None,
    limit: int = 3,
) -> list[dict]:
    """
    Look up the user's most recent prior memos that overlap with the current
    plan's tickers or themes. Used by the CIO for narrative continuity:
    "we said this 3 weeks ago — here's how it played out."

    Returns up to `limit` compact dicts: {id, query, title, decision, created_at,
    tickers, themes, executive_summary[:300]}.
    """
    if not user_id:
        return []
    try:
        from sqlalchemy import select, desc, or_
        from db.database import async_session
        from db.models import IntelligenceMemoRecord

        target_tickers = set(t.upper() for t in (tickers or []))
        target_themes = set((t or "").lower() for t in (themes or []))

        async with async_session() as session:
            # Pull recent memos for this user, post-filter for overlap.
            result = await asyncio.wait_for(
                session.execute(
                    select(IntelligenceMemoRecord)
                    .where(IntelligenceMemoRecord.user_id == user_id)
                    .order_by(desc(IntelligenceMemoRecord.created_at))
                    .limit(20)
                ),
                timeout=5.0,
            )
            memos = result.scalars().all()
    except Exception as e:
        logger.debug(f"[orchestrator] prior memos fetch failed (non-fatal): {e}")
        return []

    out: list[dict] = []
    for m in memos:
        memo_tickers = set(t.upper() for t in (m.tickers_analyzed or []))
        memo_themes = set((t or "").lower() for t in (m.themes or []))
        ticker_overlap = bool(target_tickers & memo_tickers)
        theme_overlap = bool(target_themes & memo_themes)
        if not (ticker_overlap or theme_overlap):
            continue
        out.append({
            "id": m.id,
            "query": (m.query or "")[:200],
            "title": (m.title or "")[:160],
            "executive_summary": (m.executive_summary or "")[:400],
            "macro_regime": m.macro_regime,
            "tickers": list(memo_tickers),
            "themes": list(memo_themes),
            "created_at": str(m.created_at) if m.created_at else None,
        })
        if len(out) >= limit:
            break
    return out


async def _fetch_portfolio_snapshot(user_id: str | None) -> dict | None:
    """
    Fetch a compact view of the user's existing open trades so the Strategist
    and CIO can size new ideas against the actual book. Never raises — falls
    back to None for cold-start users.
    """
    if not user_id:
        return None
    try:
        from sqlalchemy import select
        from db.database import async_session
        from db.models import TradeRecord
        from data.sector_map import resolve_sector
        from data.market_client import MarketDataClient

        mc = MarketDataClient()
        async with async_session() as session:
            result = await asyncio.wait_for(
                session.execute(
                    select(TradeRecord).where(
                        TradeRecord.status == "open",
                        TradeRecord.user_id == user_id,
                    )
                ),
                timeout=5.0,
            )
            trades = result.scalars().all()

        positions = []
        for t in trades:
            yahoo_sec = None
            try:
                fund = mc.get_fundamentals(t.ticker)
                yahoo_sec = (fund or {}).get("sector")
            except Exception:
                pass
            sector, _ = resolve_sector(t.ticker, yahoo_sec)
            positions.append({
                "ticker": t.ticker,
                "direction": t.direction,
                "size_pct": float(t.position_size_pct or 0),
                "sector": sector,
            })
        return {"open_positions": positions, "count": len(positions)}
    except Exception as e:
        logger.debug(f"[orchestrator] portfolio snapshot fetch failed (non-fatal): {e}")
        return None


async def _fetch_scorecard_for_calibration(user_id: str | None) -> dict | None:
    """
    Fetch the user's scorecard summary so the CIO can calibrate conviction
    against the system's actual track record. Returns None on any failure —
    the CIO must work without it for cold-start users.
    """
    if not user_id:
        return None
    try:
        from agents.scorer import get_scorecard_summary
        from db.database import async_session
        summary = await asyncio.wait_for(
            get_scorecard_summary(async_session, user_id=user_id),
            timeout=5.0,
        )
        if summary and summary.get("signals", 0) >= 5:
            return summary
    except Exception as e:
        logger.debug(f"[orchestrator] Scorecard fetch failed (non-fatal): {e}")
    return None


async def run_synthesizer(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "synthesizing"
    logger.info("[orchestrator] CIO Synthesizer writing memo")

    # Adaptive calibration: pull track record before invoking the CIO so it
    # can dampen conviction in low-IC buckets and reinforce high-IC ones.
    scorecard = state.get("scorecard_data")
    if scorecard is None:
        scorecard = await _fetch_scorecard_for_calibration(state.get("user_id"))
        state["scorecard_data"] = scorecard

    # Continuity context: prior memos for any ticker/theme overlap so the
    # CIO can reconcile with the user's existing narrative on this name.
    plan = state.get("plan_data") or {}
    prior_memos = await _fetch_prior_memos(
        state.get("user_id"),
        plan.get("tickers") or [],
        plan.get("themes") or [],
    )

    # Phase 1 compute stage — build the Fact Sheet the narrator must cite.
    from config import settings as _settings
    fact_sheet = None
    fact_sheet_block = ""
    if _settings.PROVENANCE_PIPELINE:
        try:
            from infra.lineage import extract_tool_lineage
            from pipeline import build_fact_sheet, fact_sheet_prompt_block
            _lineage_for_fs = extract_tool_lineage(state.get("tool_steps_by_agent") or {})
            _nlp_bundle = state.get("nlp_bundle") or {}
            # Only the SMALL changed-passage / hedged-sentence receipts go to the
            # narrator. The full-section cache receipts (20k chars each) are
            # persistence-only — appended to evidence_receipts below, never shown.
            _nlp_receipts = list(_nlp_bundle.get("receipts") or [])
            fact_sheet = build_fact_sheet(
                macro_context=state.get("macro_context"),
                strategy_data=state.get("strategy_data"),
                risk_data=state.get("risk_data"),
                live_prices=state.get("live_prices"),
                lineage=_lineage_for_fs,
                extra_receipts=_nlp_receipts,
            )
            fact_sheet_block = fact_sheet_prompt_block(fact_sheet)
        except Exception as e:
            logger.warning(f"[orchestrator] fact sheet build failed (non-fatal): {e}")

    # Capture the CIO context so the auto-repair re-prompt can reuse it.
    cio_context = {
        "plan": state["plan_data"],
        "research": state["research_data"],
        "risk": state["risk_data"],
        "strategy": state["strategy_data"],
        "scorecard": scorecard,
        "prior_memos": prior_memos,
        "macro_context": state.get("macro_context"),
        "user_context": state.get("user_context"),
        "fact_sheet_block": fact_sheet_block,
    }
    output = await _with_timeout(
        _cio_synthesizer.synthesize(cio_context),
        seconds=120, label="CIO Synthesizer"
    )
    if output is None or (output and output.error):
        err = output.error if output else "timed out"
        logger.warning(f"[orchestrator] CIO failed ({err}) — constructing memo from prior outputs")
        plan = state.get("plan_data", {})
        risk = state.get("risk_data", {})
        strategy = state.get("strategy_data", {})
        research = state.get("research_data", {})
        trade_ideas = strategy.get("trade_ideas", [])
        top_tickers = ", ".join(plan.get("tickers", [])[:4])
        state["memo_data"] = {
            "title": f"Analysis: {plan.get('query', 'Market Analysis')[:80]}",
            "executive_summary": (
                f"Macro regime: {risk.get('macro_regime', 'unknown')}. "
                f"Risk level: {risk.get('overall_risk_level', 'elevated')}. "
                f"{len(trade_ideas)} trade ideas generated for {top_tickers}. "
                f"{strategy.get('strategy_narrative', '')[:300]}"
            ),
            "analysis": research.get("data_summary", ""),
            "key_findings": [risk.get("risk_narrative", "")[:200]] if risk.get("risk_narrative") else [],
        }
    else:
        state["memo_data"] = output.output

    # Build the provenance / lineage block from every agent's accumulated
    # intermediate_steps. PMs use this to audit any claim back to a tool call.
    # Split into two try blocks so a citation failure doesn't lose lineage
    # — and so we get a clear error log if either step crashes (the catches
    # used to swallow everything to `warning` with no stack).
    memo = state.get("memo_data") or {}
    if isinstance(memo, dict):
        try:
            from infra.lineage import extract_tool_lineage
            memo["lineage"] = extract_tool_lineage(
                state.get("tool_steps_by_agent") or {}
            )
            # Pull structured outputs from prior desks into the memo dict
            # so the citation resolver sees the full picture (CIO doesn't
            # always echo trade_ideas / risk_factors).
            strategy = state.get("strategy_data") or {}
            risk = state.get("risk_data") or {}
            if isinstance(strategy, dict) and not memo.get("trade_ideas"):
                memo["trade_ideas"] = strategy.get("trade_ideas") or []
            if isinstance(risk, dict) and not memo.get("risk_factors"):
                memo["risk_factors"] = risk.get("risk_factors") or []
        except Exception as e:
            logger.exception(f"[orchestrator] lineage extraction failed: {e}")

        try:
            # Resolve every agent-emitted citation against the lineage,
            # build the deduplicated citation_index, and replace inline
            # [[src:...]] markers in prose with [N] numeric anchors.
            from infra.citations_resolver import resolve_memo_citations
            from infra.coverage import compute_coverage, grade_verification
            memo = resolve_memo_citations(memo)
            memo["coverage"] = compute_coverage(memo)
            memo["verification_status"] = grade_verification(memo["coverage"])
            stats = memo.get("_inline_marker_stats") or {}
            logger.info(
                "[orchestrator] citations: %d trade ideas, %d risk factors, "
                "%d in citation_index, markers %d/%d resolved, status=%s",
                len(memo.get("trade_ideas") or []),
                len(memo.get("risk_factors") or []),
                len(memo.get("citation_index") or []),
                stats.get("resolved", 0),
                stats.get("total", 0),
                memo.get("verification_status"),
            )
        except Exception as e:
            logger.exception(f"[orchestrator] citation resolution failed: {e}")

        # Phase 1 validate stage — lint the narrative against the Fact Sheet,
        # auto-repair orphan numbers once, then attach evidence-backed
        # footnotes + claim links. Hard-fail surfaces as verification_status
        # downgrade (the gap is shown, never silently passed).
        if _settings.PROVENANCE_PIPELINE and fact_sheet is not None and len(fact_sheet):
            try:
                from pipeline import (
                    validate_against_fact_sheet,
                    finalize_with_evidence,
                    repair_prompt_block,
                )
                vres = validate_against_fact_sheet(memo, fact_sheet)
                if (not vres.ok) and _settings.PROVENANCE_AUTO_REPAIR and (vres.orphans or vres.dangling):
                    logger.info(
                        "[orchestrator] provenance gate failed (%s); auto-repair re-prompt",
                        vres.summary(),
                    )
                    repair_ctx = dict(cio_context)
                    repair_ctx["repair_note"] = repair_prompt_block(vres.orphans, vres.dangling)
                    repair = await _with_timeout(
                        _cio_synthesizer.synthesize(repair_ctx),
                        seconds=120, label="CIO Synthesizer (repair)",
                    )
                    if repair and not repair.error and isinstance(repair.output, dict):
                        for f in ("title", "executive_summary", "analysis", "key_findings"):
                            if repair.output.get(f):
                                memo[f] = repair.output[f]
                        vres = validate_against_fact_sheet(memo, fact_sheet)

                # The Fact Sheet is AUTHORITATIVE for citations: every receipt
                # becomes a numbered citation and each trade idea / risk factor
                # gets its ticker-matched receipts — deterministically, whether
                # or not the LLM emitted markers. This is why citations always
                # appear now (the old path only surfaced LLM-cited sources).
                fin = finalize_with_evidence(memo, fact_sheet)
                memo = fin["memo"]
                memo["citation_index"] = fin["citation_index"]
                memo["evidence_receipts"] = fact_sheet.entries
                memo["evidence_links"] = fin["links"]
                # Recompute coverage/verification AGAINST the populated index.
                try:
                    from infra.coverage import compute_coverage, grade_verification
                    memo["coverage"] = compute_coverage(memo)
                    memo["verification_status"] = grade_verification(memo["coverage"])
                except Exception:
                    pass
                cov = memo.get("coverage") or {}
                cov["evidence"] = {
                    "numeric_claims": vres.numeric_claims,
                    "orphans": len(vres.orphans),
                    "dangling": len(vres.dangling),
                    "cited_evidence": len(fin["cited_ids"]),
                    "fact_sheet_entries": len(fact_sheet),
                    "ok": vres.ok,
                }
                memo["coverage"] = cov
                # Hard-fail surfaced: unresolved orphans/dangling => unverified.
                if not vres.ok:
                    memo["verification_status"] = "unverified"
                logger.info(
                    "[orchestrator] provenance: %s | citation_index=%d entries | status=%s",
                    vres.summary(), len(memo.get("citation_index") or []), memo.get("verification_status"),
                )
            except Exception as e:
                logger.exception(f"[orchestrator] provenance finalize failed: {e}")

        # Phase 2 — surface NLP coverage % on the memo (Build Plan §2.4) and
        # persist the full-section cache receipts (never shown to the narrator)
        # so future runs skip the filing fetch entirely.
        try:
            nb = state.get("nlp_bundle") or {}
            if nb.get("coverage"):
                cov = memo.get("coverage") or {}
                cov["nlp"] = nb["coverage"]
                memo["coverage"] = cov
            caches = nb.get("cache_receipts") or []
            if caches:
                memo["evidence_receipts"] = (memo.get("evidence_receipts") or []) + caches
        except Exception:
            pass
        state["memo_data"] = memo
    return state


def build_research_desk_graph() -> StateGraph:
    graph = StateGraph(ResearchDeskState)

    graph.add_node("interpreter", run_interpreter)
    graph.add_node("research", run_research)
    graph.add_node("risk", run_risk)
    graph.add_node("strategy", run_strategy)
    graph.add_node("synthesizer", run_synthesizer)

    graph.set_entry_point("interpreter")
    graph.add_edge("interpreter", "research")
    graph.add_edge("research", "risk")
    graph.add_edge("risk", "strategy")
    graph.add_edge("strategy", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph


_graph = None


def get_research_desk_graph():
    global _graph
    if _graph is None:
        _graph = build_research_desk_graph().compile()
    return _graph


async def run_research_desk(
    query: str,
    user_id: str | None = None,
    parent_memo_id: str | None = None,
) -> IntelligenceMemo:
    """Main entry point — run the full research desk pipeline on a freeform query."""
    logger.info(f"[orchestrator] Starting research desk for: {query}")

    # Resolve the user's runtime context up front. This is the single
    # load — every agent then reads it from state.user_context instead
    # of re-querying the DB. Failure-safe: returns the platform defaults
    # if the profile can't be loaded.
    from infra.user_context import resolve_user_context, resolve_user_memory
    user_ctx_obj = await resolve_user_context(user_id)
    user_ctx = dict(user_ctx_obj)
    # Augment with the user's actual usage history (watchlist + recent
    # themes/tickers). Surfaced inside the same USER CONTEXT prompt block
    # so the LLM treats "who you are" and "what you usually do" together.
    try:
        memory = await resolve_user_memory(user_id)
        if memory:
            user_ctx["memory"] = memory
    except Exception as e:
        logger.debug(f"[orchestrator] user memory fetch failed (non-fatal): {e}")

    graph = get_research_desk_graph()
    initial_state: ResearchDeskState = {
        "query": query,
        "user_id": user_id,
        "plan_data": None,
        "research_data": None,
        "risk_data": None,
        "strategy_data": None,
        "scorecard_data": None,
        "portfolio_data": None,
        "memo_data": None,
        "macro_context": None,
        "live_prices": None,
        "nlp_bundle": None,
        "data_quality": None,
        "error": None,
        "current_phase": "idle",
        "tool_steps_by_agent": None,
        "parent_memo_id": parent_memo_id,
        "thread_context": None,
        "user_context": user_ctx,
    }

    final_state = await graph.ainvoke(initial_state)

    if final_state.get("error"):
        logger.error(f"[orchestrator] Pipeline failed: {final_state['error']}")
        raise RuntimeError(final_state["error"])

    memo_data = final_state["memo_data"]
    # Merge in fields from prior stages that the CIO might not have echoed
    plan = final_state.get("plan_data", {})
    risk = final_state.get("risk_data", {})
    strategy = final_state.get("strategy_data", {})

    # CIO Synthesizer writes title, executive_summary, analysis, key_findings.
    # Structured data (risk_factors, trade_ideas, hedges) comes from prior agents
    # directly — don't trust the LLM to reconstruct structured objects from compressed text.
    memo_data["query"] = query
    memo_data["intent"] = plan.get("intent", "thematic_research")
    memo_data["tickers_analyzed"] = plan.get("tickers", [])
    memo_data["themes"] = plan.get("themes", [])
    memo_data["macro_regime"] = risk.get("macro_regime", "")
    memo_data["overall_risk_level"] = risk.get("overall_risk_level", "")
    # CITATIONS PRESERVATION: the resolver in run_synthesizer mutated
    # memo_data["trade_ideas"] and memo_data["risk_factors"] in place
    # to attach resolved citations. Only fall back to strategy/risk
    # outputs when the CIO didn't echo these structured fields at all —
    # otherwise we'd wipe the citation work.
    if not memo_data.get("risk_factors"):
        memo_data["risk_factors"] = risk.get("risk_factors", [])
    if not memo_data.get("trade_ideas"):
        memo_data["trade_ideas"] = strategy.get("trade_ideas", [])
    memo_data["portfolio_positioning"] = strategy.get("portfolio_positioning", "")
    memo_data["hedging_recommendations"] = strategy.get("hedging_recommendations", [])
    # Mandate-gate warnings: surfaced on the memo so the UI can render a
    # "MANDATE CHECK · N issues" pill. Empty list when no violations.
    memo_data["mandate_warnings"] = strategy.get("mandate_warnings", []) or []

    # Plan confidence (from Query Interpreter)
    memo_data["plan_confidence"] = int(plan.get("plan_confidence", 0) or 0)
    memo_data["plan_confidence_reason"] = plan.get("plan_confidence_reason", "") or ""

    # Plan-shape fields — surfaced in the memo so the UI can render them
    memo_data["question_type"] = plan.get("question_type", "alpha_finding")
    memo_data["benchmark"] = plan.get("benchmark", "")
    memo_data["instrument_preference"] = plan.get("instrument_preference", "stock")
    memo_data["idea_archetype"] = plan.get("idea_archetype", []) or []
    memo_data["sub_questions"] = plan.get("sub_questions", []) or []
    memo_data["falsification_criteria"] = plan.get("falsification_criteria", []) or []
    memo_data["regime_sensitivity"] = plan.get("regime_sensitivity", []) or []
    memo_data["macro_context"] = final_state.get("macro_context") or {}
    memo_data["secondary_universe"] = plan.get("secondary_universe", []) or []
    memo_data["target_idea_count"] = int(plan.get("target_idea_count", 15) or 15)
    memo_data["required_style_labels"] = plan.get("required_style_labels", []) or []

    # Phase E — thread metadata. The orchestrator sets these so the persist
    # layer can write them into the new memo row. thread_id is left None when
    # this is a fresh thread — main.py will backfill it to the memo's own id
    # after the row is inserted (so a thread with one memo is still queryable).
    tc = final_state.get("thread_context") or {}
    memo_data["thread_id"] = tc.get("thread_id")
    memo_data["parent_memo_id"] = tc.get("parent_memo_id")
    memo_data["sequence_in_thread"] = int(tc.get("sequence", 0) or 0)
    memo_data["query_class"] = plan.get("query_class", "fresh")

    # Quality + structural integrity signals
    memo_data["data_quality"] = final_state.get("data_quality") or "complete"
    research_obj = final_state.get("research_data") or {}
    if isinstance(research_obj, dict):
        memo_data["sub_question_coverage"] = research_obj.get("sub_question_coverage", []) or []
        if research_obj.get("sub_question_answered_pct") is not None:
            memo_data["sub_question_answered_pct"] = research_obj.get("sub_question_answered_pct")
    if isinstance(strategy, dict):
        memo_data["diversity"] = strategy.get("_diversity") or {}
    if isinstance(risk, dict):
        memo_data["falsification_probabilities"] = risk.get("falsification_probabilities", []) or []

    # Aggregate tool-grounding tripwire results across all desks. The worst
    # confidence wins (low > medium > high) and counts are summed so the UI
    # can show one badge that represents the whole memo's provenance quality.
    rank = {"low": 0, "medium": 1, "high": 2, "n/a": 3}
    pieces = []
    for d in (final_state.get("research_data"), risk, strategy):
        g = (d or {}).get("_grounding") if isinstance(d, dict) else None
        if g:
            pieces.append(g)
    if pieces:
        worst = min(pieces, key=lambda x: rank.get(x.get("confidence", "n/a"), 3))
        total_claims = sum(p.get("numeric_claims", 0) or 0 for p in pieces)
        total_ungrounded = sum(p.get("ungrounded_count", 0) or 0 for p in pieces)
        memo_data["grounding"] = {
            "confidence": worst.get("confidence", "n/a"),
            "numeric_claims": total_claims,
            "ungrounded_count": total_ungrounded,
            "desk_count": len(pieces),
        }

    # Run the Decision Gate (programmatic) using the user's scorecard for
    # track-record-adjusted confidence.
    try:
        from agents.desk5_decision_gate import compute_decision
        decision = compute_decision(
            trade_ideas=strategy.get("trade_ideas", []),
            macro_regime=risk.get("macro_regime", "unknown"),
            overall_risk_level=risk.get("overall_risk_level", "elevated"),
            scorecard=final_state.get("scorecard_data"),
        )
        memo_data["decision"] = decision.get("decision", "WATCH")
        memo_data["decision_reason"] = decision.get("reason", "")
        memo_data["decision_confidence"] = decision.get("confidence", 0)
    except Exception as e:
        logger.warning(f"[orchestrator] Decision gate failed: {e}")

    memo = IntelligenceMemo(**memo_data)
    logger.info(f"[orchestrator] Memo complete: {memo.title}")
    return memo
