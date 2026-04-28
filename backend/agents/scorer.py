"""
Desk 6A — Signal Scorer.

Scores every past trade idea against realized prices at 1d/5d/20d intervals.
Computes hit rates, information coefficients, and per-desk accuracy metrics.

This is the feedback loop that turns Alpha Engine from a research tool into
a learning system. Without this, there's no way to know if signals make money.
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc

from data.market_client import MarketDataClient
from db.models import IntelligenceMemoRecord, SignalScoreRecord

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def _direction_sign(direction: str) -> int:
    """Returns +1 for bullish, -1 for bearish, 0 for neutral."""
    d = (direction or "").lower()
    if "bullish" in d:
        return 1
    if "bearish" in d:
        return -1
    return 0


async def score_pending_signals(async_session_factory, user_id: str | None = None, max_scores: int = 200) -> dict:
    """
    Score all trade ideas that have aged enough but haven't been scored yet.

    For each memo:
      - Extract each trade idea
      - Check if 1d/5d/20d intervals have elapsed since memo creation
      - Fetch forward prices (via yfinance history)
      - Compute direction-adjusted returns
      - Upsert SignalScoreRecord

    If user_id is provided, only scores that user's memos.

    Returns summary of scoring job.
    """
    now = datetime.now(timezone.utc)
    cutoff_1d = now - timedelta(days=1)
    cutoff_5d = now - timedelta(days=5)
    cutoff_20d = now - timedelta(days=20)

    scored_count = 0
    updated_count = 0
    skipped = 0

    try:
        async with async_session_factory() as session:
            # Pull recent memos (last 60 days — covers 20d+ scoring window)
            memo_cutoff = now - timedelta(days=60)
            memo_q = select(IntelligenceMemoRecord).where(
                IntelligenceMemoRecord.created_at >= memo_cutoff
            )
            if user_id:
                memo_q = memo_q.where(IntelligenceMemoRecord.user_id == user_id)
            memo_q = memo_q.order_by(desc(IntelligenceMemoRecord.created_at)).limit(max_scores)
            memo_result = await session.execute(memo_q)
            memos = memo_result.scalars().all()

            for memo in memos:
                memo_date = memo.created_at
                if not memo_date:
                    continue
                # Normalize to timezone-aware
                if memo_date.tzinfo is None:
                    memo_date = memo_date.replace(tzinfo=timezone.utc)

                trade_ideas = memo.trade_ideas or []
                if not isinstance(trade_ideas, list):
                    continue

                for idea in trade_ideas:
                    if not isinstance(idea, dict):
                        continue
                    ticker = (idea.get("ticker") or "").upper().strip()
                    if not ticker:
                        continue
                    direction = idea.get("direction") or ""
                    conviction = int(idea.get("conviction") or 0)

                    # Find or create score record
                    score_q = select(SignalScoreRecord).where(
                        SignalScoreRecord.memo_id == memo.id,
                        SignalScoreRecord.ticker == ticker,
                        SignalScoreRecord.direction == direction,
                    )
                    score_result = await session.execute(score_q)
                    score = score_result.scalar_one_or_none()

                    needs_1d = memo_date <= cutoff_1d and (not score or score.price_1d is None)
                    needs_5d = memo_date <= cutoff_5d and (not score or score.price_5d is None)
                    needs_20d = memo_date <= cutoff_20d and (not score or score.price_20d is None)

                    if not (needs_1d or needs_5d or needs_20d):
                        skipped += 1
                        continue

                    # Fetch price history (enough range to cover 20d forward)
                    try:
                        history = _market.get_price_history(ticker, period="3mo")
                    except Exception as e:
                        logger.debug(f"Failed to fetch history for {ticker}: {e}")
                        continue

                    if not history:
                        continue

                    # Find entry price: closest date on/after memo_date
                    def _find_price_at_offset(days: int) -> float | None:
                        target = memo_date + timedelta(days=days)
                        # Find bar closest to target date
                        best = None
                        best_diff = None
                        for bar in history:
                            try:
                                bar_date_str = bar.get("date", "")
                                bar_date = datetime.fromisoformat(bar_date_str.split("T")[0]).replace(tzinfo=timezone.utc)
                                diff = abs((bar_date - target).total_seconds())
                                if best_diff is None or diff < best_diff:
                                    best_diff = diff
                                    best = bar.get("close")
                            except Exception:
                                continue
                        # Only accept if within 3 days of target (weekends/holidays)
                        if best_diff is not None and best_diff < 3 * 86400:
                            return best
                        return None

                    entry_price = _find_price_at_offset(0)
                    if entry_price is None or entry_price == 0:
                        continue

                    price_1d = _find_price_at_offset(1) if needs_1d else (score.price_1d if score else None)
                    price_5d = _find_price_at_offset(5) if needs_5d else (score.price_5d if score else None)
                    price_20d = _find_price_at_offset(20) if needs_20d else (score.price_20d if score else None)

                    sign = _direction_sign(direction)

                    def _ret(fwd: float | None) -> float | None:
                        if fwd is None or entry_price == 0:
                            return None
                        raw = (fwd - entry_price) / entry_price * 100
                        # Sign-adjust: positive means direction was correct
                        return round(raw * sign, 3) if sign != 0 else round(raw, 3)

                    return_1d = _ret(price_1d)
                    return_5d = _ret(price_5d)
                    return_20d = _ret(price_20d)

                    hit_1d = return_1d > 0 if return_1d is not None else None
                    hit_5d = return_5d > 0 if return_5d is not None else None
                    hit_20d = return_20d > 0 if return_20d is not None else None

                    if score is None:
                        # signal_date column is TIMESTAMP WITHOUT TIME ZONE; strip tz before write
                        signal_date_naive = memo_date.replace(tzinfo=None) if memo_date.tzinfo else memo_date
                        score = SignalScoreRecord(
                            user_id=memo.user_id,
                            memo_id=memo.id,
                            ticker=ticker,
                            direction=direction,
                            conviction=conviction,
                            entry_price=entry_price,
                            signal_date=signal_date_naive,
                            price_1d=price_1d,
                            price_5d=price_5d,
                            price_20d=price_20d,
                            return_1d=return_1d,
                            return_5d=return_5d,
                            return_20d=return_20d,
                            hit_1d=hit_1d,
                            hit_5d=hit_5d,
                            hit_20d=hit_20d,
                        )
                        session.add(score)
                        scored_count += 1
                    else:
                        if needs_1d and price_1d is not None:
                            score.price_1d = price_1d
                            score.return_1d = return_1d
                            score.hit_1d = hit_1d
                        if needs_5d and price_5d is not None:
                            score.price_5d = price_5d
                            score.return_5d = return_5d
                            score.hit_5d = hit_5d
                        if needs_20d and price_20d is not None:
                            score.price_20d = price_20d
                            score.return_20d = return_20d
                            score.hit_20d = hit_20d
                        updated_count += 1

            try:
                await session.commit()
            except Exception as commit_err:
                await session.rollback()
                logger.error(f"score_pending_signals commit failed, rolled back: {commit_err}")
                return {"scored": 0, "updated": 0, "skipped": skipped, "error": str(commit_err)}
    except Exception as e:
        logger.error(f"score_pending_signals failed: {e}")
        return {"scored": 0, "updated": 0, "skipped": 0, "error": str(e)}

    logger.info(f"Scored {scored_count} new, updated {updated_count}, skipped {skipped}")
    return {
        "scored": scored_count,
        "updated": updated_count,
        "skipped": skipped,
    }


async def get_scorecard_summary(async_session_factory, user_id: str | None = None) -> dict:
    """
    Aggregate scorecard metrics: hit rate, average return, IC per desk.

    Since we don't have per-desk signal attribution yet (all trade ideas
    come from Portfolio Desk in current pipeline), we aggregate overall
    + per-conviction-bucket metrics.
    """
    try:
        async with async_session_factory() as session:
            q = select(SignalScoreRecord).order_by(desc(SignalScoreRecord.signal_date))
            if user_id:
                q = q.where(SignalScoreRecord.user_id == user_id)
            q = q.limit(500)
            result = await session.execute(q)
            scores = result.scalars().all()
    except Exception as e:
        logger.error(f"get_scorecard_summary failed: {e}")
        return {"error": str(e), "signals": 0}

    if not scores:
        return {
            "signals": 0,
            "hit_rate_1d": None, "hit_rate_5d": None, "hit_rate_20d": None,
            "avg_return_1d": None, "avg_return_5d": None, "avg_return_20d": None,
            "ic_5d": None, "ic_20d": None,
            "by_conviction": {},
        }

    # Aggregate
    def _hit_rate(attr: str) -> float | None:
        values = [getattr(s, attr) for s in scores if getattr(s, attr) is not None]
        if not values:
            return None
        return round(sum(1 for v in values if v) / len(values) * 100, 1)

    def _avg_return(attr: str) -> float | None:
        values = [getattr(s, attr) for s in scores if getattr(s, attr) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 3)

    # Information coefficient — correlation between (direction * conviction) and return
    def _ic(return_attr: str) -> float | None:
        try:
            import numpy as np
            pairs = [
                (s.conviction * _direction_sign(s.direction), getattr(s, return_attr))
                for s in scores
                if getattr(s, return_attr) is not None and s.conviction
            ]
            if len(pairs) < 5:
                return None
            # Unsign returns: we want to check if conviction * direction predicts
            # raw return direction. Since our returns are already sign-adjusted,
            # we compute correlation between conviction (0-100) and sign-adjusted return
            x = np.array([p[0] for p in pairs], dtype=float)
            y = np.array([p[1] for p in pairs], dtype=float)
            if x.std() == 0 or y.std() == 0:
                return None
            corr = float(np.corrcoef(x, y)[0, 1])
            return round(corr, 3)
        except Exception:
            return None

    # By conviction bucket
    buckets = {"high (75+)": [], "medium (50-74)": [], "low (<50)": []}
    for s in scores:
        c = s.conviction or 0
        if c >= 75:
            buckets["high (75+)"].append(s)
        elif c >= 50:
            buckets["medium (50-74)"].append(s)
        else:
            buckets["low (<50)"].append(s)

    by_conviction = {}
    for name, bucket in buckets.items():
        if not bucket:
            by_conviction[name] = {"count": 0}
            continue
        hits_5d = [s.hit_5d for s in bucket if s.hit_5d is not None]
        rets_5d = [s.return_5d for s in bucket if s.return_5d is not None]
        by_conviction[name] = {
            "count": len(bucket),
            "hit_rate_5d": round(sum(1 for h in hits_5d if h) / len(hits_5d) * 100, 1) if hits_5d else None,
            "avg_return_5d": round(sum(rets_5d) / len(rets_5d), 3) if rets_5d else None,
        }

    # Top winners and losers
    sorted_by_20d = sorted(
        [s for s in scores if s.return_20d is not None],
        key=lambda s: s.return_20d or 0,
        reverse=True,
    )
    top_winners = [
        {
            "ticker": s.ticker,
            "direction": s.direction,
            "conviction": s.conviction,
            "return_20d": s.return_20d,
            "signal_date": s.signal_date.isoformat() if s.signal_date else None,
        }
        for s in sorted_by_20d[:5]
    ]
    top_losers = [
        {
            "ticker": s.ticker,
            "direction": s.direction,
            "conviction": s.conviction,
            "return_20d": s.return_20d,
            "signal_date": s.signal_date.isoformat() if s.signal_date else None,
        }
        for s in sorted_by_20d[-5:][::-1] if s.return_20d is not None and s.return_20d < 0
    ]

    return {
        "signals": len(scores),
        "hit_rate_1d": _hit_rate("hit_1d"),
        "hit_rate_5d": _hit_rate("hit_5d"),
        "hit_rate_20d": _hit_rate("hit_20d"),
        "avg_return_1d": _avg_return("return_1d"),
        "avg_return_5d": _avg_return("return_5d"),
        "avg_return_20d": _avg_return("return_20d"),
        "ic_5d": _ic("return_5d"),
        "ic_20d": _ic("return_20d"),
        "by_conviction": by_conviction,
        "top_winners": top_winners,
        "top_losers": top_losers,
    }
