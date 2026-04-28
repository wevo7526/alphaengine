"""
Backtesting Engine — walk-forward simulation with slippage and commission.

Two modes:
1. Signal Replay: replay historical ConsensusSignals against price data
2. Rules-Based: proxy agent logic with pure Python functions (no LLM)

All vectorized with numpy. No look-ahead bias.
"""

import numpy as np
import math
import logging
from datetime import date
from data.market_client import MarketDataClient
from quant.performance import full_performance_report, drawdown_series

logger = logging.getLogger(__name__)

_market = MarketDataClient()


class BacktestConfig:
    def __init__(
        self,
        initial_capital: float = 100000,
        slippage_bps: float = 5.0,
        commission_bps: float = 2.0,
        max_positions: int = 10,
        max_position_size: float = 0.05,
        risk_free_rate: float | None = None,
    ):
        self.initial_capital = initial_capital
        self.slippage_bps = slippage_bps
        self.commission_bps = commission_bps
        self.max_positions = max_positions
        self.max_position_size = max_position_size
        # Resolve from FRED if not explicitly set, so backtest Sharpe is
        # computed against the actual current rate environment.
        if risk_free_rate is None:
            try:
                from data.fred_client import FREDDataClient
                self.risk_free_rate = FREDDataClient().get_risk_free_rate()
            except Exception:
                self.risk_free_rate = 0.04
        else:
            self.risk_free_rate = risk_free_rate


def _apply_slippage(price: float, direction: int, bps: float) -> float:
    """Apply slippage. direction=1 for buy, -1 for sell."""
    return price * (1 + direction * bps / 10000)


def _scaled_slippage_bps(
    base_bps: float,
    notional: float,
    avg_volume_shares: float | None,
    price: float,
) -> float:
    """
    Scale slippage with participation rate. Realistic market-impact models
    (Almgren-Chriss et al.) say impact grows ~ sqrt(participation_rate). For
    a small-cap with $5M ADV, a $50k order = 1% of ADV ≈ ~0bp extra. A
    $500k order = 10% of ADV ≈ ~30bp extra above the baseline. This makes
    backtests honest about how big a position can actually be filled at the
    posted price.
    """
    if not avg_volume_shares or avg_volume_shares <= 0 or price <= 0:
        return base_bps
    adv_dollars = avg_volume_shares * price
    participation = max(0.0, notional / adv_dollars)
    # Square-root market impact, scaled so 10% participation adds 30bp
    impact = 95.0 * math.sqrt(participation)
    return base_bps + impact


def run_rules_based_backtest(
    tickers: list[str],
    period: str = "1y",
    config: BacktestConfig | None = None,
) -> dict:
    """
    Rules-based backtest using technical proxy signals (no LLM).

    Strategy: simple momentum + mean reversion signals computed from price data.
    - RSI < 30 + price above 200-day MA = buy signal (oversold in uptrend)
    - RSI > 70 + price below 200-day MA = sell signal (overbought in downtrend)
    - Position sizing: equal weight, capped at max_position_size
    """
    if config is None:
        config = BacktestConfig()

    # Fetch total-return-adjusted price data (splits + dividends reinvested).
    # Using raw close would understate returns on dividend-paying names by
    # 2-5%/year over multi-year tests.
    all_prices = {}
    for ticker in tickers[:10]:  # Cap at 10 to conserve API
        try:
            history = _market.get_total_return_history(ticker, period=period)
            if history and len(history) > 50:
                all_prices[ticker] = history
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker}: {e}")

    if not all_prices:
        return {"error": "No price data available"}

    # Fetch SPY total-return as benchmark — apples-to-apples vs strategy
    try:
        spy_history = _market.get_total_return_history("SPY", period=period)
    except Exception:
        spy_history = None

    # Walk forward
    capital = config.initial_capital
    positions: dict[str, dict] = {}  # ticker → {shares, entry_price, entry_idx}
    equity_curve = [capital]
    trades = []

    # Use the ticker with the most data points as the time axis
    max_bars = max(len(h) for h in all_prices.values())
    min_bars = min(len(h) for h in all_prices.values())
    n_bars = min_bars  # Align to shortest series

    for i in range(50, n_bars):  # Start at 50 to have enough history for indicators
        daily_pnl = 0

        for ticker, history in all_prices.items():
            if i >= len(history):
                continue

            # AVOID LOOK-AHEAD BIAS: compute signals using ONLY data through
            # bar i-1 (yesterday's close), then execute on bar i (today's close).
            # In live trading you observe RSI/MA at end-of-day-(i-1) and can
            # fill on day-i's open/close at the earliest. Using close[i]
            # for both signal AND execution silently inflates returns.
            closes_prior = [bar["close"] for bar in history[:i]]
            if len(closes_prior) < 15:
                continue
            execution_price = history[i]["close"]  # fill at today's close

            # RSI (14-period) on yesterday's close history
            deltas = np.diff(closes_prior[-15:])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses)
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi = 100 - (100 / (1 + rs))

            # SMA(50) on yesterday's history
            ma50 = float(np.mean(closes_prior[-50:])) if len(closes_prior) >= 50 else float(closes_prior[-1])

            # Signal logic — uses yesterday's last close vs the same MA
            last_close = closes_prior[-1]
            signal = 0
            if rsi < 35 and last_close > ma50:
                signal = 1
            elif rsi > 65 and last_close < ma50:
                signal = -1

            # Execute on today's close (no look-ahead because the signal
            # only consumed data through bar i-1).
            current_price = execution_price
            avg_vol_today = float(history[i].get("volume") or 0)
            if signal == 1 and ticker not in positions and len(positions) < config.max_positions:
                # Buy
                size_pct = min(config.max_position_size, 1.0 / config.max_positions)
                dollar_amount = capital * size_pct
                slip_bps = _scaled_slippage_bps(
                    config.slippage_bps, dollar_amount, avg_vol_today, current_price,
                )
                exec_price = _apply_slippage(current_price, 1, slip_bps)
                shares = dollar_amount / exec_price
                cost = dollar_amount * config.commission_bps / 10000

                positions[ticker] = {
                    "shares": shares,
                    "entry_price": exec_price,
                    "entry_idx": i,
                    "cost": cost,
                }
                capital -= dollar_amount + cost

            elif signal == -1 and ticker in positions:
                # Sell
                pos = positions.pop(ticker)
                proceeds_at_mid = pos["shares"] * current_price
                slip_bps = _scaled_slippage_bps(
                    config.slippage_bps, proceeds_at_mid, avg_vol_today, current_price,
                )
                exec_price = _apply_slippage(current_price, -1, slip_bps)
                proceeds = pos["shares"] * exec_price
                cost = proceeds * config.commission_bps / 10000
                pnl = proceeds - pos["shares"] * pos["entry_price"] - pos["cost"] - cost

                capital += proceeds - cost
                trades.append({
                    "ticker": ticker,
                    "entry_price": round(pos["entry_price"], 2),
                    "exit_price": round(exec_price, 2),
                    "shares": round(pos["shares"], 2),
                    "pnl_dollars": round(pnl, 2),
                    "pnl_pct": round(pnl / (pos["shares"] * pos["entry_price"]) * 100, 2),
                    "holding_days": i - pos["entry_idx"],
                })

        # Mark-to-market
        positions_value = sum(
            pos["shares"] * all_prices[t][min(i, len(all_prices[t]) - 1)]["close"]
            for t, pos in positions.items()
            if i < len(all_prices[t])
        )
        total_value = capital + positions_value
        equity_curve.append(round(total_value, 2))

    # Close remaining positions at last price
    for ticker, pos in list(positions.items()):
        last_price = all_prices[ticker][-1]["close"]
        exec_price = _apply_slippage(last_price, -1, config.slippage_bps)
        proceeds = pos["shares"] * exec_price
        pnl = proceeds - pos["shares"] * pos["entry_price"] - pos["cost"]
        capital += proceeds
        trades.append({
            "ticker": ticker,
            "entry_price": round(pos["entry_price"], 2),
            "exit_price": round(exec_price, 2),
            "shares": round(pos["shares"], 2),
            "pnl_dollars": round(pnl, 2),
            "pnl_pct": round(pnl / (pos["shares"] * pos["entry_price"]) * 100, 2),
            "holding_days": n_bars - pos["entry_idx"],
        })

    # Compute returns
    returns = []
    for i in range(1, len(equity_curve)):
        r = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        returns.append(r)

    # Benchmark returns
    benchmark_returns = None
    benchmark_return_pct = None
    benchmark_sharpe = None
    if spy_history and len(spy_history) >= n_bars:
        spy_closes = [bar["close"] for bar in spy_history[:n_bars]]
        benchmark_returns = [(spy_closes[i] - spy_closes[i - 1]) / spy_closes[i - 1] for i in range(1, len(spy_closes))]
        benchmark_return_pct = round((spy_closes[-1] / spy_closes[0] - 1) * 100, 2) if spy_closes else None
        from quant.performance import sharpe_ratio as sr
        benchmark_sharpe = sr(benchmark_returns)

    # Full performance report
    report = full_performance_report(
        equity_curve=equity_curve,
        returns=returns,
        trades=trades,
        benchmark_returns=benchmark_returns,
        risk_free_rate=config.risk_free_rate,
    )

    report["equity_curve"] = [{"index": i, "value": v} for i, v in enumerate(equity_curve)]
    report["drawdown_series"] = [{"index": i, "dd": d} for i, d in enumerate(drawdown_series(equity_curve))]
    report["trades"] = trades
    report["tickers"] = list(all_prices.keys())
    report["initial_capital"] = config.initial_capital
    report["final_value"] = equity_curve[-1] if equity_curve else config.initial_capital
    report["benchmark_return_pct"] = benchmark_return_pct
    report["benchmark_sharpe"] = benchmark_sharpe
    report["n_bars"] = n_bars

    return report
