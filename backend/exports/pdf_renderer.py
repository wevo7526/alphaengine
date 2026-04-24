"""
PDF export renderer — builds Alpha Engine PDFs for memos, portfolios,
scans, scorecards, morning briefings, and date-range bundles.

Uses ReportLab Platypus (pure Python, no system deps — works on Railway).
"""

import io
import logging
from datetime import datetime, timezone
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, PageBreak,
    KeepTogether, Flowable, HRFlowable,
)
from reportlab.platypus.doctemplate import BaseDocTemplate, PageTemplate, Frame
from reportlab.pdfgen import canvas

from .styles import (
    build_styles, table_bordered_header, table_statcards,
    decision_color, severity_color, direction_color, pnl_color,
    INK, INK_MUTED, INK_GHOST, DIVIDER, ACCENT, GREEN, RED, YELLOW,
)
from .charts import correlation_heatmap, drawdown_chart, attribution_decomposition, conviction_hit_rate

logger = logging.getLogger(__name__)

S = build_styles()
PAGE_W, PAGE_H = LETTER
MARGIN_X = 0.6 * inch
MARGIN_Y = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN_X


# ── Page decorations ─────────────────────────────────────────────

class _HeaderFooterCanvas(canvas.Canvas):
    """Canvas subclass that draws header/footer on every page."""

    def __init__(self, *args, report_title: str = "Alpha Engine", report_subtitle: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []
        self._report_title = report_title
        self._report_subtitle = report_subtitle

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for i, state in enumerate(self._saved_pages):
            self.__dict__.update(state)
            self._draw_header_footer(i + 1, total)
            super().showPage()
        super().save()

    def _draw_header_footer(self, page_num: int, page_total: int):
        # Header
        self.saveState()
        self.setFillColor(INK)
        self.setFont("Helvetica-Bold", 8.5)
        self.drawString(MARGIN_X, PAGE_H - 0.4 * inch, f"ALPHA ENGINE  ·  {self._report_title.upper()}")
        if self._report_subtitle:
            self.setFillColor(INK_MUTED)
            self.setFont("Helvetica", 8)
            self.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 0.4 * inch, self._report_subtitle)
        self.setStrokeColor(DIVIDER)
        self.setLineWidth(0.4)
        self.line(MARGIN_X, PAGE_H - 0.5 * inch, PAGE_W - MARGIN_X, PAGE_H - 0.5 * inch)

        # Footer
        self.setFillColor(INK_GHOST)
        self.setFont("Helvetica", 7.5)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.drawString(MARGIN_X, 0.4 * inch, f"Generated {now}")
        self.drawRightString(PAGE_W - MARGIN_X, 0.4 * inch, f"Page {page_num} of {page_total}")
        self.drawCentredString(PAGE_W / 2, 0.4 * inch, "alpha-engine · confidential")
        self.restoreState()


def _make_doc(buf: io.BytesIO, title: str, subtitle: str = "") -> SimpleDocTemplate:
    """Create a SimpleDocTemplate with our page margins + header/footer hook."""
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=0.8 * inch, bottomMargin=0.7 * inch,
        title=f"Alpha Engine — {title}",
        author="Alpha Engine",
    )
    doc._report_title = title
    doc._report_subtitle = subtitle
    return doc


def _build(buf: io.BytesIO, title: str, subtitle: str, story: list):
    """Build the PDF with consistent canvas class."""
    doc = _make_doc(buf, title, subtitle)

    def _canvas_maker(*args, **kwargs):
        return _HeaderFooterCanvas(*args, report_title=title, report_subtitle=subtitle, **kwargs)

    doc.build(story, canvasmaker=_canvas_maker)


# ── Shared flowable helpers ──────────────────────────────────────

class DecisionBadge(Flowable):
    """A colored pill-shaped GO/NO-GO/WATCH badge."""

    def __init__(self, decision: str, width=60, height=20):
        super().__init__()
        self.decision = (decision or "WATCH").upper()
        self.width = width
        self.height = height

    def wrap(self, *args):
        return self.width, self.height

    def draw(self):
        bg, fg = decision_color(self.decision)
        self.canv.saveState()
        self.canv.setFillColor(bg)
        self.canv.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=0)
        self.canv.setFillColor(fg)
        self.canv.setFont("Helvetica-Bold", 9)
        self.canv.drawCentredString(self.width / 2, self.height / 2 - 3, self.decision)
        self.canv.restoreState()


def _divider(thickness: float = 0.4) -> Flowable:
    return HRFlowable(width="100%", thickness=thickness, color=DIVIDER, spaceBefore=4, spaceAfter=6)


def _stat_cards(cards: list[tuple[str, str, colors.Color | None]]) -> Table:
    """Row of stat cards: list of (label, value, optional color)."""
    from reportlab.lib.enums import TA_LEFT
    cells = []
    for label, value, val_color in cards:
        val_style = S["Title"].clone("val")
        val_style.fontSize = 14
        val_style.leading = 17
        val_style.textColor = val_color or INK
        val_style.alignment = TA_LEFT

        cell = [
            Paragraph(label.upper(), S["Small"]),
            Spacer(1, 2),
            Paragraph(value, val_style),
        ]
        cells.append(cell)

    tbl = Table([cells], colWidths=[CONTENT_W / len(cards)] * len(cards))
    tbl.setStyle(table_statcards())
    return tbl


def _escape(text: Any) -> str:
    """Escape HTML for Paragraph text."""
    if text is None:
        return ""
    s = str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ══════════════════════════════════════════════════════════════════
# MEMO EXPORT
# ══════════════════════════════════════════════════════════════════

def render_memo(memo: dict) -> bytes:
    """Render a single intelligence memo to PDF bytes."""
    buf = io.BytesIO()
    title_text = memo.get("title") or memo.get("query", "Intelligence Memo")[:100]
    subtitle = memo.get("query", "")[:80]

    story: list = []

    # Header block: decision badge + title
    decision = memo.get("decision", "WATCH")
    conf = memo.get("decision_confidence", 0)

    header_tbl = Table(
        [[DecisionBadge(decision), Paragraph(f"<b>{_escape(title_text)}</b>", S["Title"])]],
        colWidths=[0.9 * inch, CONTENT_W - 0.9 * inch],
    )
    header_tbl.setStyle(TableStyle_NoBorder())
    story.append(header_tbl)

    meta_parts = []
    if memo.get("macro_regime"):
        meta_parts.append(f"Macro: <b>{_escape(memo['macro_regime']).replace('_', ' ')}</b>")
    if memo.get("overall_risk_level"):
        meta_parts.append(f"Risk: <b>{_escape(memo['overall_risk_level'])}</b>")
    if conf:
        meta_parts.append(f"Conviction: <b>{conf}</b>")
    if memo.get("created_at"):
        meta_parts.append(f"Date: {memo['created_at'][:10]}")

    story.append(Paragraph("  ·  ".join(meta_parts), S["Subtitle"]))

    if memo.get("decision_reason"):
        story.append(Paragraph(f"<i>{_escape(memo['decision_reason'])}</i>", S["Quote"]))

    story.append(_divider())

    # Executive Summary
    story.append(Paragraph("EXECUTIVE SUMMARY", S["SectionHeader"]))
    exec_sum = memo.get("executive_summary") or "—"
    story.append(Paragraph(_escape(exec_sum), S["BodyJustified"]))

    # Key Findings
    findings = memo.get("key_findings", [])
    if findings:
        story.append(Paragraph("KEY FINDINGS", S["SectionHeader"]))
        for i, f in enumerate(findings[:8], 1):
            story.append(Paragraph(f"<b>{i}.</b>  {_escape(f)}", S["BulletItem"]))

    # Analysis (full prose)
    analysis = memo.get("analysis") or ""
    if analysis:
        story.append(PageBreak())
        story.append(Paragraph("ANALYSIS", S["SectionHeader"]))
        for para in analysis.split("\n\n"):
            para = para.strip()
            if para:
                story.append(Paragraph(_escape(para), S["BodyJustified"]))

    # Trade Ideas
    trade_ideas = memo.get("trade_ideas", [])
    if trade_ideas:
        story.append(PageBreak())
        story.append(Paragraph("TRADE IDEAS", S["SectionHeader"]))

        for i, idea in enumerate(trade_ideas[:8], 1):
            direction = idea.get("direction", "neutral")
            dir_color = direction_color(direction)
            side = "LONG" if "bullish" in direction else "SHORT" if "bearish" in direction else "NEUTRAL"

            header = Paragraph(
                f"<b>#{i}  <font color='#09090b'>{_escape(idea.get('ticker', '?'))}</font></b>  "
                f"<font color='{dir_color.hexval()}'><b>{side}</b></font>  "
                f"<font color='#71717a'>· conviction {idea.get('conviction', 0)}</font>",
                S["H3"],
            )
            story.append(header)
            story.append(Paragraph(_escape(idea.get("thesis", "")), S["Body"]))

            rows = [
                ["Entry", idea.get("entry_zone") or "—",
                 "Stop", f"${idea.get('stop_loss')}" if idea.get("stop_loss") else "—"],
                ["Target", f"${idea.get('take_profit')}" if idea.get("take_profit") else "—",
                 "R/R", f"{idea.get('risk_reward_ratio')}:1" if idea.get("risk_reward_ratio") else "—"],
                ["Size", f"{idea.get('position_size_pct', 0)}%",
                 "Horizon", idea.get("time_horizon") or "weeks"],
            ]
            tbl = Table(rows, colWidths=[0.7 * inch, 1.8 * inch, 0.7 * inch, 1.8 * inch])
            tbl.setStyle(TableStyle_MetaGrid())
            story.append(tbl)

            if idea.get("catalysts"):
                catalysts = idea["catalysts"] if isinstance(idea["catalysts"], list) else [idea["catalysts"]]
                story.append(Paragraph(
                    f"<b>Catalysts:</b> {_escape('; '.join(str(c) for c in catalysts[:3]))}",
                    S["Small"],
                ))
            story.append(Spacer(1, 8))

    # Risk Factors
    risk_factors = memo.get("risk_factors", [])
    if risk_factors:
        story.append(PageBreak())
        story.append(Paragraph("RISK FACTORS", S["SectionHeader"]))

        for rf in risk_factors[:10]:
            sev = rf.get("severity", "medium")
            sev_c = severity_color(sev)
            cat = rf.get("category", "").upper()
            head = Paragraph(
                f"<font color='{sev_c.hexval()}'><b>[{_escape(sev)}]</b></font>  "
                f"<b>{_escape(cat)}</b>",
                S["Body"],
            )
            story.append(head)
            desc = rf.get("description", "")
            if desc:
                story.append(Paragraph(_escape(desc), S["Small"]))
            mit = rf.get("mitigation", "")
            if mit:
                story.append(Paragraph(f"<i>Mitigation: {_escape(mit)}</i>", S["Small"]))
            story.append(Spacer(1, 6))

    # Hedging
    hedges = memo.get("hedging_recommendations", [])
    if hedges:
        story.append(Paragraph("HEDGING RECOMMENDATIONS", S["SectionHeader"]))
        for i, h in enumerate(hedges[:6], 1):
            story.append(Paragraph(f"<b>H{i}.</b>  {_escape(h)}", S["BulletItem"]))

    _build(buf, "Intelligence Memo", title_text[:80], story)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════
# PORTFOLIO EXPORT
# ══════════════════════════════════════════════════════════════════

def render_portfolio(
    positions: list[dict],
    summary: dict,
    attribution: dict | None = None,
    scorecard: dict | None = None,
) -> bytes:
    """Full portfolio report."""
    buf = io.BytesIO()
    story: list = []

    story.append(Paragraph("Portfolio Report", S["Title"]))
    story.append(Paragraph(
        f"Total Value ${summary.get('total_market_value', 0):,.0f}  ·  "
        f"{summary.get('open_positions', 0)} open positions  ·  "
        f"{summary.get('closed_trades', 0)} closed",
        S["Subtitle"],
    ))
    story.append(_divider())

    # Summary stats
    cards = [
        ("Total Value", f"${summary.get('total_market_value', 0):,.0f}", None),
        ("Unrealized P&L",
         f"{'+' if (summary.get('total_unrealized_pnl_pct') or 0) >= 0 else ''}{summary.get('total_unrealized_pnl_pct', 0):.2f}%",
         pnl_color(summary.get("total_unrealized_pnl"))),
        ("Realized P&L",
         f"${summary.get('total_realized_pnl', 0):,.0f}",
         pnl_color(summary.get("total_realized_pnl"))),
        ("Win Rate",
         f"{summary.get('win_rate', 0):.1f}%" if summary.get("win_rate") is not None else "—",
         GREEN if (summary.get("win_rate") or 0) >= 50 else RED),
    ]
    story.append(_stat_cards(cards))
    story.append(Spacer(1, 14))

    # Positions table
    if positions:
        story.append(Paragraph("OPEN POSITIONS", S["SectionHeader"]))
        head = ["Ticker", "Dir", "Entry", "Current", "P&L %", "P&L $", "Weight", "Stop / Target"]
        rows = [head]
        for p in positions:
            dir_label = "LONG" if "bullish" in (p.get("direction") or "") else "SHORT" if "bearish" in (p.get("direction") or "") else "—"
            pnl = p.get("unrealized_pnl_pct")
            pnl_str = f"{'+' if (pnl or 0) >= 0 else ''}{pnl:.2f}%" if pnl is not None else "—"
            pnl_d = p.get("unrealized_pnl_dollars")
            pnl_d_str = f"${'+' if (pnl_d or 0) >= 0 else ''}{pnl_d:.0f}" if pnl_d is not None else "—"
            weight = p.get("weight_pct") or p.get("total_size_pct", 0)
            stop = p.get("avg_stop_loss")
            tgt = p.get("avg_take_profit")
            stop_tgt = f"${stop:.0f} / ${tgt:.0f}" if stop and tgt else "—"
            rows.append([
                p.get("ticker", "—"),
                dir_label,
                f"${p.get('avg_entry_price'):.2f}" if p.get("avg_entry_price") else "—",
                f"${p.get('current_price'):.2f}" if p.get("current_price") else "—",
                pnl_str,
                pnl_d_str,
                f"{weight:.1f}%",
                stop_tgt,
            ])

        col_widths = [
            0.7 * inch, 0.6 * inch, 0.75 * inch, 0.8 * inch,
            0.75 * inch, 0.85 * inch, 0.7 * inch, 1.15 * inch,
        ]
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        style = table_bordered_header()
        # Color P&L columns
        for i, p in enumerate(positions, 1):
            pnl = p.get("unrealized_pnl_pct")
            if pnl is not None:
                c = GREEN if pnl >= 0 else RED
                style.add("TEXTCOLOR", (4, i), (5, i), c)
        tbl.setStyle(style)
        story.append(tbl)

    # Attribution
    if attribution and not attribution.get("error"):
        story.append(PageBreak())
        story.append(Paragraph("P&L ATTRIBUTION", S["SectionHeader"]))

        decomp = attribution.get("decomposition", {}) or {}
        img = attribution_decomposition(
            decomp.get("alpha_pct") or 0,
            decomp.get("beta_contribution_pct") or 0,
            decomp.get("residual_pct") or 0,
            width_pts=CONTENT_W,
        )
        if img:
            story.append(img)
            story.append(Spacer(1, 10))

        fl = attribution.get("factor_loadings", {})
        rows = [
            ["Alpha (annualized)", f"{fl.get('alpha'):+.2f}%" if fl.get("alpha") is not None else "—"],
            ["Beta (vs SPY)", f"{fl.get('beta'):.3f}" if fl.get("beta") is not None else "—"],
            ["R-Squared", f"{fl.get('r_squared'):.3f}" if fl.get("r_squared") is not None else "—"],
            ["Residual Volatility", f"{fl.get('residual_vol'):.2f}%" if fl.get("residual_vol") is not None else "—"],
            ["Period Return", f"{attribution.get('period_return_pct'):+.2f}%" if attribution.get("period_return_pct") is not None else "—"],
            ["SPY Benchmark", f"{attribution.get('benchmark_return_pct'):+.2f}%" if attribution.get("benchmark_return_pct") is not None else "—"],
        ]
        tbl = Table(rows, colWidths=[2.2 * inch, 1.8 * inch])
        tbl.setStyle(TableStyle_MetaGrid())
        story.append(tbl)

    # Scorecard summary
    if scorecard and scorecard.get("signals", 0) > 0:
        story.append(PageBreak())
        story.append(Paragraph("SIGNAL SCORECARD", S["SectionHeader"]))
        cards2 = [
            ("Signals Scored", str(scorecard.get("signals", 0)), None),
            ("Hit Rate (5d)",
             f"{scorecard.get('hit_rate_5d')}%" if scorecard.get("hit_rate_5d") is not None else "—",
             GREEN if (scorecard.get("hit_rate_5d") or 0) >= 55 else RED),
            ("Hit Rate (20d)",
             f"{scorecard.get('hit_rate_20d')}%" if scorecard.get("hit_rate_20d") is not None else "—",
             GREEN if (scorecard.get("hit_rate_20d") or 0) >= 55 else RED),
            ("IC (5d)",
             f"{scorecard.get('ic_5d'):.3f}" if scorecard.get("ic_5d") is not None else "—",
             None),
        ]
        story.append(_stat_cards(cards2))
        story.append(Spacer(1, 14))

        img = conviction_hit_rate(scorecard.get("by_conviction", {}), width_pts=CONTENT_W)
        if img:
            story.append(img)

    _build(buf, "Portfolio Report", f"{summary.get('open_positions', 0)} positions", story)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════
# SCAN DIGEST
# ══════════════════════════════════════════════════════════════════

def render_scan(findings_by_priority: dict, run_meta: dict) -> bytes:
    """Scan digest PDF."""
    buf = io.BytesIO()
    story: list = []

    story.append(Paragraph("Overnight Scan Digest", S["Title"]))
    story.append(Paragraph(
        f"{run_meta.get('findings_count', 0)} findings across {run_meta.get('universe_size', 0)} tickers  ·  "
        f"completed {run_meta.get('completed_at', 'unknown')[:19] if run_meta.get('completed_at') else 'unknown'}",
        S["Subtitle"],
    ))
    story.append(_divider())

    priority_order = [("high", "HIGH PRIORITY", RED),
                      ("medium", "SIGNALS", YELLOW),
                      ("low", "LOW PRIORITY", INK_MUTED)]

    for key, label, color in priority_order:
        items = findings_by_priority.get(key, [])
        if not items:
            continue
        story.append(Paragraph(f"<font color='{color.hexval()}'><b>{label}</b></font>  ({len(items)})", S["SectionHeader"]))

        for f in items:
            head = Paragraph(
                f"<b>{_escape(f.get('ticker', '?'))}</b>  "
                f"<font color='#71717a'>· {_escape(f.get('finding_type', '?'))}</font>",
                S["Body"],
            )
            story.append(head)
            story.append(Paragraph(_escape(f.get("headline", "")), S["Body"]))
            if f.get("detail"):
                story.append(Paragraph(_escape(f["detail"]), S["Small"]))
            story.append(Spacer(1, 6))

    _build(buf, "Scan Digest", "", story)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════
# SCORECARD
# ══════════════════════════════════════════════════════════════════

def render_scorecard(summary: dict, signals: list[dict]) -> bytes:
    """Signal scorecard PDF."""
    buf = io.BytesIO()
    story: list = []

    story.append(Paragraph("Signal Scorecard", S["Title"]))
    story.append(Paragraph(
        f"{summary.get('signals', 0)} signals scored at 1d / 5d / 20d intervals",
        S["Subtitle"],
    ))
    story.append(_divider())

    cards = [
        ("Hit Rate (1d)",
         f"{summary.get('hit_rate_1d')}%" if summary.get("hit_rate_1d") is not None else "—",
         GREEN if (summary.get("hit_rate_1d") or 0) >= 55 else RED if (summary.get("hit_rate_1d") or 0) < 45 else None),
        ("Hit Rate (5d)",
         f"{summary.get('hit_rate_5d')}%" if summary.get("hit_rate_5d") is not None else "—",
         GREEN if (summary.get("hit_rate_5d") or 0) >= 55 else RED if (summary.get("hit_rate_5d") or 0) < 45 else None),
        ("Hit Rate (20d)",
         f"{summary.get('hit_rate_20d')}%" if summary.get("hit_rate_20d") is not None else "—",
         GREEN if (summary.get("hit_rate_20d") or 0) >= 55 else RED if (summary.get("hit_rate_20d") or 0) < 45 else None),
        ("IC (20d)",
         f"{summary.get('ic_20d'):.3f}" if summary.get("ic_20d") is not None else "—",
         None),
    ]
    story.append(_stat_cards(cards))
    story.append(Spacer(1, 14))

    # By conviction bar chart
    img = conviction_hit_rate(summary.get("by_conviction", {}), width_pts=CONTENT_W)
    if img:
        story.append(img)
        story.append(Spacer(1, 10))

    # Top winners
    winners = summary.get("top_winners") or []
    losers = summary.get("top_losers") or []

    if winners:
        story.append(Paragraph("TOP WINNERS (20d)", S["SectionHeader"]))
        for w in winners:
            story.append(Paragraph(
                f"<b>{_escape(w.get('ticker'))}</b>  "
                f"<font color='#71717a'>{_escape(w.get('direction'))}  ·  conv {w.get('conviction')}</font>  "
                f"<font color='#059669'><b>+{w.get('return_20d'):.2f}%</b></font>",
                S["Body"],
            ))

    if losers:
        story.append(Paragraph("TOP LOSERS (20d)", S["SectionHeader"]))
        for l in losers:
            story.append(Paragraph(
                f"<b>{_escape(l.get('ticker'))}</b>  "
                f"<font color='#71717a'>{_escape(l.get('direction'))}  ·  conv {l.get('conviction')}</font>  "
                f"<font color='#dc2626'><b>{l.get('return_20d'):.2f}%</b></font>",
                S["Body"],
            ))

    # Recent signals table
    if signals:
        story.append(PageBreak())
        story.append(Paragraph("RECENT SIGNALS", S["SectionHeader"]))
        head = ["Ticker", "Dir", "Conv", "Date", "Ret 5d", "Ret 20d", "Hit 20d"]
        rows = [head]
        for s in signals[:30]:
            ret5 = s.get("return_5d")
            ret20 = s.get("return_20d")
            hit20 = s.get("hit_20d")
            rows.append([
                s.get("ticker", "—"),
                "LONG" if "bullish" in (s.get("direction") or "") else "SHORT" if "bearish" in (s.get("direction") or "") else "—",
                str(s.get("conviction", "—")),
                (s.get("signal_date") or "")[:10],
                f"{ret5:+.2f}%" if ret5 is not None else "—",
                f"{ret20:+.2f}%" if ret20 is not None else "—",
                "✓" if hit20 is True else "✗" if hit20 is False else "—",
            ])
        tbl = Table(rows, colWidths=[0.7, 0.6, 0.6, 0.9, 0.8, 0.8, 0.7], repeatRows=1)
        for i in range(len(tbl._argW)):
            tbl._argW[i] = tbl._argW[i] * inch
        tbl.setStyle(table_bordered_header())
        story.append(tbl)

    _build(buf, "Signal Scorecard", f"{summary.get('signals', 0)} signals", story)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════
# MORNING BRIEFING
# ══════════════════════════════════════════════════════════════════

def render_morning_briefing(report: dict) -> bytes:
    """Morning pre-market briefing — essentially a memo with slightly different framing."""
    # Reuse memo renderer — morning report is stored as a memo structure
    return render_memo(report)


# ══════════════════════════════════════════════════════════════════
# DATE-RANGE BUNDLE
# ══════════════════════════════════════════════════════════════════

def render_range_bundle(
    start_date: str,
    end_date: str,
    memos: list[dict],
    trades: list[dict],
    positions: list[dict],
    summary: dict,
    scorecard: dict | None = None,
) -> bytes:
    """Comprehensive date-range export: all memos + trade journal + P&L snapshot."""
    buf = io.BytesIO()
    story: list = []

    story.append(Paragraph("Alpha Engine Archive", S["Title"]))
    story.append(Paragraph(
        f"{start_date} to {end_date}  ·  {len(memos)} memos  ·  {len(trades)} trades",
        S["Subtitle"],
    ))
    story.append(_divider())

    # Summary overview
    cards = [
        ("Memos", str(len(memos)), None),
        ("Trades", str(len(trades)), None),
        ("Realized P&L",
         f"${summary.get('total_realized_pnl', 0):,.0f}",
         pnl_color(summary.get("total_realized_pnl"))),
        ("Win Rate",
         f"{summary.get('win_rate', 0):.1f}%" if summary.get("win_rate") is not None else "—",
         None),
    ]
    story.append(_stat_cards(cards))
    story.append(Spacer(1, 14))

    # Memo titles
    if memos:
        story.append(Paragraph("MEMOS IN PERIOD", S["SectionHeader"]))
        for m in memos:
            story.append(Paragraph(
                f"<b>{(m.get('created_at') or '')[:10]}</b>  ·  "
                f"<b>{_escape(m.get('title') or m.get('query', '')[:80])}</b>  "
                f"<font color='#71717a'>· decision: {m.get('decision', 'WATCH')}</font>",
                S["Body"],
            ))

    # Trades
    if trades:
        story.append(PageBreak())
        story.append(Paragraph("TRADE JOURNAL", S["SectionHeader"]))
        head = ["Ticker", "Dir", "Entry", "Exit", "Size%", "Realized", "Status", "Date"]
        rows = [head]
        for t in trades:
            pnl = t.get("realized_pnl")
            rows.append([
                t.get("ticker", "—"),
                t.get("action") or "—",
                f"${t.get('entry_price'):.2f}" if t.get("entry_price") else "—",
                f"${t.get('exit_price'):.2f}" if t.get("exit_price") else "—",
                f"{t.get('position_size_pct', 0):.1f}%",
                f"{pnl:+.2f}%" if pnl is not None else "—",
                t.get("status", "—"),
                (t.get("opened_at") or "")[:10],
            ])
        col_widths = [0.7, 0.6, 0.75, 0.75, 0.6, 0.75, 0.7, 0.9]
        tbl = Table(rows, colWidths=[w * inch for w in col_widths], repeatRows=1)
        style = table_bordered_header()
        for i, t in enumerate(trades, 1):
            pnl = t.get("realized_pnl")
            if pnl is not None:
                style.add("TEXTCOLOR", (5, i), (5, i), GREEN if pnl >= 0 else RED)
        tbl.setStyle(style)
        story.append(tbl)

    # Scorecard summary if provided
    if scorecard and scorecard.get("signals", 0) > 0:
        story.append(PageBreak())
        story.append(Paragraph("PERFORMANCE", S["SectionHeader"]))
        cards2 = [
            ("Hit Rate (5d)",
             f"{scorecard.get('hit_rate_5d')}%" if scorecard.get("hit_rate_5d") is not None else "—",
             None),
            ("Avg Return (5d)",
             f"{scorecard.get('avg_return_5d'):+.2f}%" if scorecard.get("avg_return_5d") is not None else "—",
             pnl_color(scorecard.get("avg_return_5d"))),
            ("IC (5d)",
             f"{scorecard.get('ic_5d'):.3f}" if scorecard.get("ic_5d") is not None else "—",
             None),
            ("Signals",
             str(scorecard.get("signals", 0)),
             None),
        ]
        story.append(_stat_cards(cards2))

    _build(buf, "Archive Bundle", f"{start_date} → {end_date}", story)
    buf.seek(0)
    return buf.read()


# ── Small TableStyles as functions to avoid ReportLab class-level shared state ──

def TableStyle_NoBorder():
    from reportlab.platypus import TableStyle as TS
    return TS([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ])


def TableStyle_MetaGrid():
    from reportlab.platypus import TableStyle as TS
    return TS([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), INK_MUTED),
        ("TEXTCOLOR", (2, 0), (2, -1), INK_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), INK),
        ("TEXTCOLOR", (3, 0), (3, -1), INK),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


# Ensure TableStyle import available inside the closures above
from reportlab.platypus import TableStyle
