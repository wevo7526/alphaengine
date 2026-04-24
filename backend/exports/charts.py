"""
Chart generators for PDF exports — matplotlib backend renders to PNG buffer
that ReportLab embeds via its Image flowable.

All charts are print-friendly: light background, clear labels, no interactive
elements. Matplotlib is used headlessly (Agg backend).
"""

import io
import logging

import matplotlib
matplotlib.use("Agg")  # Headless — no Tk/Qt
import matplotlib.pyplot as plt
import numpy as np

from reportlab.platypus import Image

logger = logging.getLogger(__name__)

# Typography defaults matching the PDF body
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 9,
    "axes.edgecolor": "#d4d4d8",
    "axes.labelcolor": "#3f3f46",
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "xtick.color": "#71717a",
    "ytick.color": "#71717a",
    "axes.grid": True,
    "grid.color": "#f4f4f5",
    "grid.linewidth": 0.5,
})


def _fig_to_image(fig, width_pts: float = 450) -> Image:
    """Render a matplotlib figure to a ReportLab Image sized by width in points."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf, width=width_pts, height=None)
    img._restrictSize(width_pts, 10000)
    return img


def correlation_heatmap(tickers: list[str], matrix: list[list[float]], width_pts: float = 450) -> Image | None:
    """Correlation matrix as a heatmap. Returns None if insufficient data."""
    try:
        if not tickers or not matrix or len(matrix) != len(tickers):
            return None
        n = len(tickers)
        arr = np.array([[float(c or 0) for c in row] for row in matrix])

        fig, ax = plt.subplots(figsize=(max(4, n * 0.8), max(3, n * 0.7)))
        im = ax.imshow(arr, cmap="RdBu_r", vmin=-1, vmax=1, aspect="equal")

        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(tickers, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(tickers, fontsize=8)

        # Write values in cells
        for i in range(n):
            for j in range(n):
                val = arr[i, j]
                color = "white" if abs(val) > 0.6 else "#09090b"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=7, color=color)

        ax.set_title("Return Correlation Matrix", pad=10)
        fig.colorbar(im, ax=ax, shrink=0.7, label="ρ")
        return _fig_to_image(fig, width_pts)
    except Exception as e:
        logger.warning(f"correlation_heatmap failed: {e}")
        return None


def drawdown_chart(ticker: str, series: list[dict], width_pts: float = 450) -> Image | None:
    """Drawdown from peak for a single ticker."""
    try:
        if not series:
            return None
        dates = [i for i in range(len(series))]
        values = [s.get("drawdown", 0) for s in series]

        fig, ax = plt.subplots(figsize=(6, 2.2))
        ax.fill_between(dates, values, 0, color="#fecaca", alpha=0.6)
        ax.plot(dates, values, color="#dc2626", linewidth=1.2)
        ax.axhline(0, color="#a1a1aa", linewidth=0.5)
        ax.set_title(f"{ticker} — Drawdown from Peak", pad=8)
        ax.set_ylabel("DD %", fontsize=8)
        ax.set_xlabel("")
        ax.set_xticks([])
        return _fig_to_image(fig, width_pts)
    except Exception as e:
        logger.warning(f"drawdown_chart failed for {ticker}: {e}")
        return None


def sparkline(ticker: str, closes: list[float], width_pts: float = 150) -> Image | None:
    """Small price sparkline for embedded ticker cards."""
    try:
        if not closes or len(closes) < 2:
            return None
        fig, ax = plt.subplots(figsize=(2.5, 0.9))
        x = list(range(len(closes)))
        color = "#059669" if closes[-1] >= closes[0] else "#dc2626"
        ax.plot(x, closes, color=color, linewidth=1.3)
        ax.fill_between(x, closes, min(closes), color=color, alpha=0.15)
        ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        return _fig_to_image(fig, width_pts)
    except Exception as e:
        logger.warning(f"sparkline failed for {ticker}: {e}")
        return None


def attribution_decomposition(alpha_pct: float, beta_pct: float, residual_pct: float, width_pts: float = 450) -> Image | None:
    """Horizontal stacked bar: alpha vs beta contribution vs residual."""
    try:
        fig, ax = plt.subplots(figsize=(6, 1.5))
        components = [("Alpha (skill)", alpha_pct or 0, "#059669"),
                      ("Beta × Market", beta_pct or 0, "#3b82f6"),
                      ("Residual", residual_pct or 0, "#ca8a04")]
        y = 0
        left_pos = 0
        left_neg = 0
        for label, val, color in components:
            if val >= 0:
                ax.barh(y, val, left=left_pos, color=color, edgecolor="white", linewidth=0.5, label=label)
                if abs(val) > 0.3:
                    ax.text(left_pos + val / 2, y, f"{val:+.1f}%", ha="center", va="center", fontsize=8, color="white", fontweight="bold")
                left_pos += val
            else:
                left_neg += val
                ax.barh(y, val, left=left_neg - val, color=color, edgecolor="white", linewidth=0.5, label=label)
                if abs(val) > 0.3:
                    ax.text(left_neg - val / 2, y, f"{val:+.1f}%", ha="center", va="center", fontsize=8, color="white", fontweight="bold")

        ax.set_yticks([])
        ax.set_xlabel("% return contribution", fontsize=8)
        ax.set_title("P&L Decomposition", pad=6)
        ax.axvline(0, color="#71717a", linewidth=0.5)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.4), ncol=3, fontsize=8, frameon=False)
        ax.grid(axis="x", linewidth=0.3, color="#f4f4f5")
        return _fig_to_image(fig, width_pts)
    except Exception as e:
        logger.warning(f"attribution_decomposition failed: {e}")
        return None


def conviction_hit_rate(buckets: dict, width_pts: float = 450) -> Image | None:
    """Bar chart: hit rate by conviction bucket."""
    try:
        labels = []
        values = []
        for name, stats in buckets.items():
            rate = stats.get("hit_rate_5d")
            if rate is None:
                continue
            labels.append(name)
            values.append(rate)
        if not labels:
            return None

        fig, ax = plt.subplots(figsize=(5, 2.2))
        colors_list = ["#059669" if v >= 55 else "#dc2626" if v < 45 else "#ca8a04" for v in values]
        bars = ax.bar(labels, values, color=colors_list, edgecolor="white", linewidth=0.5)
        ax.axhline(50, color="#71717a", linewidth=0.5, linestyle="--")
        ax.set_ylabel("Hit rate %", fontsize=8)
        ax.set_title("Hit Rate by Conviction (5d)", pad=6)
        ax.set_ylim(0, 100)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 2, f"{val:.0f}%",
                    ha="center", fontsize=8, color="#3f3f46")
        return _fig_to_image(fig, width_pts)
    except Exception as e:
        logger.warning(f"conviction_hit_rate failed: {e}")
        return None
