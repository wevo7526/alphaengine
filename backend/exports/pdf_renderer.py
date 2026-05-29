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
    PAPER_SOFT,
)
from .charts import (
    correlation_heatmap, drawdown_chart, attribution_decomposition,
    conviction_hit_rate, trade_idea_conviction_distribution,
)

logger = logging.getLogger(__name__)

S = build_styles()
PAGE_W, PAGE_H = LETTER
MARGIN_X = 0.6 * inch
MARGIN_Y = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN_X


# ── Page decorations ─────────────────────────────────────────────

class _HeaderFooterCanvas(canvas.Canvas):
    """Canvas subclass that draws header/footer on every page.

    Skips the header on page 1 (cover page) so the cover treatment can
    own the top of the page without competing with a section bar.
    """

    def __init__(
        self,
        *args,
        report_title: str = "Alpha Engine",
        report_subtitle: str = "",
        suppress_first_page_header: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._saved_pages = []
        self._report_title = report_title
        self._report_subtitle = report_subtitle
        self._suppress_first_header = suppress_first_page_header

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
        self.saveState()

        # Header — skip on the cover page so the cover hero can breathe.
        if not (self._suppress_first_header and page_num == 1):
            # Two-tone wordmark: "ALPHA " (ink) + "ENGINE" (accent)
            self.setFillColor(INK)
            self.setFont("Helvetica-Bold", 8.5)
            self.drawString(MARGIN_X, PAGE_H - 0.4 * inch, "ALPHA ")
            cursor = MARGIN_X + self.stringWidth("ALPHA ", "Helvetica-Bold", 8.5)
            self.setFillColor(ACCENT)
            self.drawString(cursor, PAGE_H - 0.4 * inch, "ENGINE")
            cursor += self.stringWidth("ENGINE", "Helvetica-Bold", 8.5)
            # Report title in muted weight after the wordmark — short label
            # only (e.g. "Intelligence Memo"); subtitle goes on the right.
            self.setFillColor(INK_MUTED)
            self.setFont("Helvetica", 8.5)
            title_seg = f"  ·  {self._report_title}"
            self.drawString(cursor, PAGE_H - 0.4 * inch, title_seg)
            cursor += self.stringWidth(title_seg, "Helvetica", 8.5)

            if self._report_subtitle:
                self.setFillColor(INK_MUTED)
                self.setFont("Helvetica", 8)
                # Reserve a 0.4" buffer so the subtitle never touches the
                # report_title text on the left. Truncate hard with an
                # ellipsis when needed.
                max_w = PAGE_W - MARGIN_X - cursor - 0.4 * inch
                sub = self._report_subtitle
                ellipsis_w = self.stringWidth("…", "Helvetica", 8)
                # Iteratively trim until the string + ellipsis fits.
                if self.stringWidth(sub, "Helvetica", 8) > max_w:
                    while sub and self.stringWidth(sub, "Helvetica", 8) + ellipsis_w > max_w and len(sub) > 6:
                        sub = sub[:-1]
                    sub = sub.rstrip(" -—·") + "…"
                if max_w > 20:  # Only draw if there's room to be readable
                    self.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 0.4 * inch, sub)
            self.setStrokeColor(DIVIDER)
            self.setLineWidth(0.4)
            self.line(MARGIN_X, PAGE_H - 0.5 * inch, PAGE_W - MARGIN_X, PAGE_H - 0.5 * inch)

        # Footer — every page, including cover.
        self.setFillColor(INK_GHOST)
        self.setFont("Helvetica", 7.5)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.drawString(MARGIN_X, 0.4 * inch, f"Generated {now}")
        self.drawRightString(PAGE_W - MARGIN_X, 0.4 * inch, f"Page {page_num} of {page_total}")
        self.drawCentredString(PAGE_W / 2, 0.4 * inch, "alpha-engine  ·  confidential")
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


def _build(
    buf: io.BytesIO,
    title: str,
    subtitle: str,
    story: list,
    suppress_first_page_header: bool = False,
):
    """Build the PDF with consistent canvas class.

    `suppress_first_page_header` is used by memo exports so the cover
    hero on page 1 has full vertical real estate.
    """
    doc = _make_doc(buf, title, subtitle)

    def _canvas_maker(*args, **kwargs):
        return _HeaderFooterCanvas(
            *args,
            report_title=title,
            report_subtitle=subtitle,
            suppress_first_page_header=suppress_first_page_header,
            **kwargs,
        )

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


def _trim_for_header(text: str, max_chars: int = 65) -> str:
    """Trim a long string to a word boundary and append an ellipsis.

    Used for the continuation-page header subtitle so a long memo title
    never gets cut mid-word and never reaches the page edge.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    space = cut.rfind(" ")
    if space > max_chars * 0.6:
        cut = cut[:space]
    return cut.rstrip(" -—·,;:") + "…"


# ══════════════════════════════════════════════════════════════════
# MEMO EXPORT
# ══════════════════════════════════════════════════════════════════

# ── Memo-specific flowables ──

class _CoverBand(Flowable):
    """Brand band that anchors the top of the cover page.

    Two-tone wordmark on the left, eyebrow + date on the right, with a
    thin accent rule beneath. Replaces the tiny default page header on
    the cover so the title can lead.
    """

    def __init__(self, eyebrow: str, date_text: str, width: float):
        super().__init__()
        self.eyebrow = eyebrow
        self.date_text = date_text
        self.width = width
        self.height = 36

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(0, 18, "ALPHA ")
        w = c.stringWidth("ALPHA ", "Helvetica-Bold", 13)
        c.setFillColor(ACCENT)
        c.drawString(w, 18, "ENGINE")

        # Right side — eyebrow + date stacked
        c.setFillColor(INK_MUTED)
        c.setFont("Courier-Bold", 8)
        c.drawRightString(self.width, 22, self.eyebrow)
        c.setFillColor(INK_GHOST)
        c.setFont("Helvetica", 8)
        c.drawRightString(self.width, 10, self.date_text)

        # Accent rule + ghost rule for the band
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.4)
        c.line(0, 4, 56, 4)
        c.setStrokeColor(DIVIDER)
        c.setLineWidth(0.4)
        c.line(56, 4, self.width, 4)
        c.restoreState()


class _ConvictionBar(Flowable):
    """Slim horizontal bar showing 0–100 conviction next to a trade idea."""

    def __init__(self, value: int, width: float = 110, height: float = 6):
        super().__init__()
        self.value = max(0, min(100, int(value or 0)))
        self.width = width
        self.height = height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        # Track
        c.setFillColor(DIVIDER)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, fill=1, stroke=0)
        # Fill — green if ≥70, yellow 50–69, red <50
        if self.value >= 70:
            fill = GREEN
        elif self.value >= 50:
            fill = YELLOW
        else:
            fill = RED
        c.setFillColor(fill)
        fill_w = max(self.height, self.width * self.value / 100)
        c.roundRect(0, 0, fill_w, self.height, self.height / 2, fill=1, stroke=0)
        c.restoreState()


def _section_title(label: str) -> Table:
    """Section header: `///` accent + uppercase label + ghost rule."""
    style = ParagraphStyle_section_eyebrow()
    eyebrow = Paragraph(
        f"<font color='{ACCENT.hexval()}'>///</font>  <b>{_escape(label.upper())}</b>",
        style,
    )
    rule = HRFlowable(width="100%", thickness=0.5, color=DIVIDER, spaceBefore=0, spaceAfter=0)
    tbl = Table([[eyebrow], [rule]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle_NoBorder())
    return tbl


def ParagraphStyle_section_eyebrow():
    """Hover-style section eyebrow used by _section_title."""
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "SectionEyebrow",
        fontName="Helvetica-Bold", fontSize=10, leading=14,
        textColor=INK, spaceBefore=8, spaceAfter=4,
        letterSpacing=1.2,
    )


def _kpi_strip(
    items: list[tuple[str, str, colors.Color | None]],
    total_width: float | None = None,
) -> Table:
    """Cover-page KPI row. Each item: (label, value, optional value color).

    `total_width` defaults to CONTENT_W but the cover passes a narrower
    value because the KPI strip sits next to the decision badge — using
    CONTENT_W there made the rightmost card hang off the page edge.
    """
    if total_width is None:
        total_width = CONTENT_W
    cells = []
    for label, value, val_color in items:
        val_style = S["KPIValue"].clone("kpiVal")
        if val_color is not None:
            val_style.textColor = val_color
        cells.append([
            Paragraph(label.upper(), S["KPILabel"]),
            Spacer(1, 2),
            Paragraph(value, val_style),
        ])
    tbl = Table([cells], colWidths=[total_width / max(1, len(items))] * len(items))
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
        ("LINEAFTER", (0, 0), (-2, -1), 0.4, DIVIDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return tbl


# Trade-idea card uses 14pt LEFT/RIGHT padding on its outer border. Inner
# tables (head row, stat strip) must reserve that 28pt or they spill past
# the card border — that was the visible "lines bleeding off cards" bug.
_CARD_PADDING = 14
INNER_W = CONTENT_W - 2 * _CARD_PADDING


def _trade_idea_card(idea: dict, index: int) -> KeepTogether:
    """Bordered card for a single trade idea — header, thesis, stat strip, catalysts."""
    direction = (idea.get("direction") or "neutral").lower()
    side = "LONG" if "bullish" in direction else "SHORT" if "bearish" in direction else "NEUTRAL"
    dir_color = direction_color(direction)
    conviction = int(idea.get("conviction") or 0)

    # Visible ticker is capped so very long symbols (BERKSHIRE-HATHAWAY-B,
    # foreign listings, share-class suffixes) don't blow out the card
    # header and run into the direction pill.
    raw_ticker = (idea.get("ticker") or "?").strip()
    display_ticker = raw_ticker if len(raw_ticker) <= 10 else raw_ticker[:9] + "…"
    ticker = _escape(display_ticker)
    thesis = _escape(idea.get("thesis") or "")

    # Header row: #N ticker · direction pill · conviction bar
    direction_pill = Paragraph(
        f"<font color='{dir_color.hexval()}' size='8'><b>{side}</b></font>",
        ParagraphStyle_pill(dir_color),
    )
    ticker_line = Paragraph(
        f"<font color='{INK_MUTED.hexval()}' size='9'>#{index}</font>  "
        f"<font color='{INK.hexval()}' size='14'><b>{ticker}</b></font>",
        S["Body"],
    )

    bar = _ConvictionBar(conviction, width=110, height=6)
    bar_label = Paragraph(
        f"<font color='{INK_MUTED.hexval()}' size='7'><b>CONV</b></font>  "
        f"<font color='{INK.hexval()}' size='10'><b>{conviction}</b></font>",
        S["Body"],
    )

    head_tbl = Table(
        [[ticker_line, direction_pill, [bar_label, Spacer(1, 2), bar]]],
        colWidths=[INNER_W * 0.45, INNER_W * 0.20, INNER_W * 0.35],
    )
    head_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    thesis_para = Paragraph(thesis, S["IdeaThesis"])

    # Stat strip: 6 metrics in a single bordered row. ENTRY gets a wider
    # column because entry zones are the longest values ("$523.78 to
    # $550.64 wide range"); the other 5 columns get equal smaller widths.
    entry_raw = (idea.get("entry_zone") or "—")
    # Cap the entry zone too — overly verbose ranges from the LLM are the
    # main cause of cell wrapping. 28 chars fits the wider column nicely.
    entry = entry_raw if len(entry_raw) <= 28 else entry_raw[:27] + "…"
    stop = f"${idea['stop_loss']}" if idea.get("stop_loss") else "—"
    target = f"${idea['take_profit']}" if idea.get("take_profit") else "—"
    rr = f"{idea['risk_reward_ratio']}:1" if idea.get("risk_reward_ratio") else "—"
    size = f"{idea.get('position_size_pct', 0)}%"
    horizon = idea.get("time_horizon") or "weeks"

    def _cell(label: str, value: str) -> list:
        return [
            Paragraph(label, S["CardLabel"]),
            Paragraph(_escape(value), S["CardValue"]),
        ]

    # ENTRY column gets ~25% of inner width; others share the remaining 75%.
    # Using INNER_W (not CONTENT_W) so the strip stays inside the card border.
    entry_w = INNER_W * 0.25
    other_w = (INNER_W - entry_w) / 5
    stat_tbl = Table(
        [[
            _cell("ENTRY", entry),
            _cell("STOP", stop),
            _cell("TARGET", target),
            _cell("R/R", rr),
            _cell("SIZE", size),
            _cell("HORIZON", horizon),
        ]],
        colWidths=[entry_w, other_w, other_w, other_w, other_w, other_w],
    )
    stat_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.4, DIVIDER),
        ("LINEAFTER", (0, 0), (-2, -1), 0.4, DIVIDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    body_flowables = [head_tbl, Spacer(1, 4), thesis_para, stat_tbl]

    catalysts = idea.get("catalysts")
    if catalysts:
        cats = catalysts if isinstance(catalysts, list) else [catalysts]
        # Cap at 3 catalysts to keep the card height predictable.
        cat_text = " · ".join(str(c) for c in cats[:3])
        if len(cats) > 3:
            cat_text += f"  (+{len(cats) - 3} more)"
        body_flowables.append(Spacer(1, 6))
        body_flowables.append(Paragraph(
            f"<font color='{INK_MUTED.hexval()}'><b>CATALYSTS</b></font> &nbsp; "
            f"{_escape(cat_text)}",
            S["Small"],
        ))

    # Wrap the card in an outer single-cell table so we get a clean border
    # AND can use KeepTogether so a card never splits across pages.
    # Padding constant matches _CARD_PADDING used to compute INNER_W above.
    outer = Table([[body_flowables]], colWidths=[CONTENT_W])
    outer.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, DIVIDER),
        ("LEFTPADDING", (0, 0), (-1, -1), _CARD_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), _CARD_PADDING),
        ("TOPPADDING", (0, 0), (-1, -1), _CARD_PADDING),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _CARD_PADDING),
    ]))
    return KeepTogether([outer, Spacer(1, 10)])


def ParagraphStyle_pill(color):
    """Inline style helper for the direction pill in trade-idea headers."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    return ParagraphStyle(
        "Pill", fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=color, alignment=TA_CENTER,
    )


_SECONDARY_BUCKETS = frozenset({"mid_cap", "small_cap", "micro_cap"})


def _is_secondary_idea(idea: dict) -> bool:
    """Classify a trade idea as core vs secondary for the rendering split.

    Mirrors the frontend `isSecondaryIdea` so in-app and exported memos
    partition the same way. Any of tier ≥ 2, mid/small/micro-cap bucket,
    or screen_source set marks the idea as secondary. Untagged ideas
    default to core (safe for legacy memos).
    """
    if not isinstance(idea, dict):
        return False
    tier = idea.get("tier")
    try:
        if tier is not None and int(tier) >= 2:
            return True
    except (TypeError, ValueError):
        pass
    bucket = (idea.get("market_cap_bucket") or "").lower()
    if bucket in _SECONDARY_BUCKETS:
        return True
    if idea.get("screen_source"):
        return True
    return False


def _risk_factor_block(rf: dict) -> KeepTogether:
    """One risk factor — left severity bar + colored severity tag + content."""
    sev = (rf.get("severity") or "medium").lower()
    sev_color = severity_color(sev)
    cat = (rf.get("category") or "").upper() or "RISK"

    # Header: colored severity pill + uppercase category
    head = Paragraph(
        f"<font color='{sev_color.hexval()}' face='Courier-Bold' size='8'>"
        f"[{sev.upper()}]</font>  "
        f"<font color='{INK.hexval()}' size='10'><b>{_escape(cat)}</b></font>",
        S["Body"],
    )
    desc = rf.get("description") or ""
    mit = rf.get("mitigation") or ""

    body = [head]
    if desc:
        body.append(Paragraph(_escape(desc), S["IdeaThesis"]))
    if mit:
        body.append(Paragraph(
            f"<font color='{INK_MUTED.hexval()}'><b>Mitigation:</b></font>  <i>{_escape(mit)}</i>",
            S["Small"],
        ))

    # Two-column layout: left = severity color bar, right = content
    outer = Table(
        [[Spacer(0, 0), body]],
        colWidths=[3.5, CONTENT_W - 3.5],
    )
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), sev_color),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 12),
        ("RIGHTPADDING", (1, 0), (1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return KeepTogether([outer, Spacer(1, 6)])


def _plan_shape_block(memo: dict) -> list:
    """Render PLAN SHAPE — Interpreter's structural directives.

    Returns a list of flowables. Empty list when no plan shape fields
    were emitted (older memos).
    """
    qt = memo.get("question_type") or ""
    bench = memo.get("benchmark") or ""
    instr = memo.get("instrument_preference") or ""
    archetype = memo.get("idea_archetype") or []
    target_n = memo.get("target_idea_count")
    required_styles = memo.get("required_style_labels") or []
    secondary = memo.get("secondary_universe") or []

    if not (qt or bench or instr or archetype or target_n or required_styles or secondary):
        return []

    flows: list = [_section_title("Plan Shape")]

    # Key-value 2×N table for the structural fields
    rows: list = []
    if qt:
        rows.append(("Question type", qt.replace("_", " ")))
    if bench:
        rows.append(("Benchmark", bench))
    if instr:
        rows.append(("Instrument preference", instr.replace("_", " ")))
    if target_n:
        rows.append(("Target idea count", str(target_n)))
    if rows:
        kv_tbl = Table(
            [[Paragraph(_escape(k), S["CardLabel"]), Paragraph(_escape(v), S["CardValue"])]
             for k, v in rows],
            colWidths=[1.6 * inch, CONTENT_W - 1.6 * inch],
        )
        kv_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, DIVIDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        flows.append(kv_tbl)
        flows.append(Spacer(1, 8))

    # Archetype + style coverage as pill rows so they don't bleed off the page
    if archetype:
        flows.append(Paragraph(
            f"<font color='{INK_MUTED.hexval()}'><b>ARCHETYPE DIRECTIVE</b></font>",
            S["Small"],
        ))
        flows.append(Paragraph(_escape(" · ".join(archetype)), S["Body"]))
        flows.append(Spacer(1, 4))

    if required_styles:
        covered = set((memo.get("diversity") or {}).get("styles_covered") or [])
        items = []
        for s in required_styles:
            mark = "✓" if s in covered else "✗"
            color = GREEN if s in covered else RED
            items.append(f"<font color='{color.hexval()}'>{mark}</font> {_escape(s.replace('_', ' '))}")
        flows.append(Paragraph(
            f"<font color='{INK_MUTED.hexval()}'><b>REQUIRED STYLE COVERAGE</b></font>",
            S["Small"],
        ))
        flows.append(Paragraph("  ·  ".join(items), S["Body"]))
        flows.append(Spacer(1, 4))

    if secondary:
        flows.append(Paragraph(
            f"<font color='{INK_MUTED.hexval()}'><b>SECONDARY UNIVERSE</b></font> "
            f"<font color='{INK_GHOST.hexval()}'>· non-mega-cap candidates</font>",
            S["Small"],
        ))
        flows.append(Paragraph(_escape(", ".join(secondary[:25])), S["Mono"]))
        flows.append(Spacer(1, 6))

    return flows


def _open_questions_block(memo: dict) -> list:
    """Render OPEN QUESTIONS — sub-question coverage with ✓/? markers.

    Mirrors the in-app Sub-Questions panel so the PDF reader sees the
    same answered / unanswered breakdown.
    """
    coverage = memo.get("sub_question_coverage") or []
    if not coverage:
        return []
    answered = sum(1 for c in coverage if isinstance(c, dict) and c.get("answered"))
    total = len(coverage)
    flows: list = [
        _section_title(f"Open Questions  ·  {answered} of {total} addressed"),
    ]
    for c in coverage:
        if not isinstance(c, dict):
            continue
        q = c.get("question") or ""
        ok = bool(c.get("answered"))
        mark_color = GREEN if ok else YELLOW
        mark = "✓" if ok else "?"
        flows.append(Paragraph(
            f"<font color='{mark_color.hexval()}' face='Courier-Bold' size='10'>{mark}</font> "
            f"&nbsp; <font color='{INK_SOFT.hexval() if ok else INK_MUTED.hexval()}'>"
            f"{_escape(q)}</font>",
            S["BulletItem"],
        ))
    return flows


def _falsification_block(memo: dict) -> list:
    """Render WHAT WOULD CHANGE OUR VIEW — falsification criteria + probs."""
    criteria = memo.get("falsification_criteria") or []
    probs = memo.get("falsification_probabilities") or []
    if not criteria:
        return []
    prob_map: dict[str, str] = {}
    for p in probs:
        if isinstance(p, dict) and p.get("criterion"):
            prob_map[p["criterion"]] = (p.get("probability") or "").lower()
    flows: list = [_section_title("What Would Change Our View")]
    for c in criteria:
        if not isinstance(c, str):
            continue
        prob = prob_map.get(c)
        pc = (
            RED if prob == "high" else GREEN if prob == "low"
            else YELLOW if prob == "medium" else INK_MUTED
        )
        tag = (
            f"<font color='{pc.hexval()}' face='Courier-Bold' size='8'>"
            f"[{prob.upper()}]</font> &nbsp; " if prob else ""
        )
        flows.append(Paragraph(
            f"{tag}<font color='{INK_SOFT.hexval()}'>{_escape(c)}</font>",
            S["BulletItem"],
        ))
    return flows


def _regime_sensitivity_block(memo: dict) -> list:
    """Render REGIME SENSITIVITY — Strategist's per-regime positioning view."""
    rs = memo.get("regime_sensitivity") or []
    if not rs:
        return []
    current = ((memo.get("macro_context") or {}).get("current_regime") or "").lower()
    flows: list = [_section_title("Regime Sensitivity")]
    rows = []
    head = [
        Paragraph("REGIME", S["CardLabel"]),
        Paragraph("IDEAL POSITION", S["CardLabel"]),
        Paragraph("SIZE ×", S["CardLabel"]),
        Paragraph("KEY ASSUMPTION", S["CardLabel"]),
    ]
    rows.append(head)
    for r in rs:
        if not isinstance(r, dict):
            continue
        regime = (r.get("regime") or "—").lower()
        ideal = r.get("ideal_position") or "—"
        mult = r.get("conviction_multiplier")
        mult_s = f"×{mult}" if mult is not None else "—"
        assume = r.get("key_assumption") or "—"
        is_cur = regime == current
        regime_label = f"{regime} ★" if is_cur else regime
        regime_para = Paragraph(
            f"<font color='{ACCENT.hexval() if is_cur else INK.hexval()}'>"
            f"<b>{_escape(regime_label)}</b></font>",
            S["Body"],
        )
        rows.append([
            regime_para,
            Paragraph(_escape(ideal), S["Body"]),
            Paragraph(_escape(mult_s), S["Body"]),
            Paragraph(_escape(assume), S["IdeaThesis"]),
        ])
    tbl = Table(
        rows,
        colWidths=[1.3 * inch, 2.4 * inch, 0.7 * inch, CONTENT_W - 4.4 * inch],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PAPER_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, DIVIDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flows.append(tbl)
    return flows


def _citation_index_block(memo: dict) -> list:
    """Render CITATIONS — the deduplicated numbered footnote index.

    This is the in-app CitationIndexPanel equivalent for the PDF. Empty
    list when the memo carries no citation_index (legacy or uncited).
    """
    index = memo.get("citation_index") or []
    if not index:
        return []
    flows: list = [_section_title(f"Citations  ·  {len(index)}")]
    for c in index[:40]:
        if not isinstance(c, dict):
            continue
        n = c.get("n") or 0
        label = c.get("label") or c.get("source_id") or "—"
        source_id = c.get("source_id") or ""
        excerpt = c.get("excerpt") or ""
        url = c.get("url")
        line = (
            f"<font color='{ACCENT.hexval()}' face='Courier-Bold' size='9'>[{n}]</font> "
            f"&nbsp; <font color='{INK_SOFT.hexval()}' size='9'>{_escape(label)}</font>"
        )
        # Receipt provenance: the named formula / accession behind the figure.
        if source_id and source_id != label:
            line += (
                f" &nbsp; <font color='{INK_SOFT.hexval()}' face='Courier' size='7.5'>"
                f"{_escape(source_id)}</font>"
            )
        if url:
            line += (
                f" &nbsp; <font color='{ACCENT.hexval()}' size='7.5'>"
                f"<link href='{_escape(url)}'>OPEN &#8594;</link></font>"
            )
        flows.append(Paragraph(line, S["SourceItem"]))
        # Verbatim passage / computed-at note as a muted sub-line.
        if excerpt:
            flows.append(Paragraph(
                f"<font color='{INK_SOFT.hexval()}' size='7.5'>{_escape(excerpt[:240])}</font>",
                S["SourceItem"],
            ))
    return flows


def _source_ledger(lineage: dict | None) -> list:
    """Render the memo's source/provenance section.

    Returns a list of flowables. Empty list when there's nothing to show.
    """
    if not lineage or not isinstance(lineage, dict):
        return []
    sources = lineage.get("sources") or []
    if not sources:
        return []

    # Group by type for readability
    by_type: dict[str, list[dict]] = {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        t = src.get("type") or "other"
        by_type.setdefault(t, []).append(src)

    type_labels = {
        "sec_filing": "SEC FILINGS",
        "sec_insider": "INSIDER TRADES (FORM 4)",
        "sec_13f": "13F HOLDINGS",
        "fred_series": "FRED MACRO SERIES",
        "market_price": "MARKET DATA",
        "news_article": "NEWS",
        "web_search": "WEB RESEARCH",
        "technical": "TECHNICAL INDICATORS",
        "screen": "DISCOVERY SCREENS",
        "computed": "COMPUTED ANALYTICS",
        "other": "OTHER",
    }

    n_calls = lineage.get("n_tool_calls", 0)
    n_unique = lineage.get("n_unique_sources", len(sources))

    flowables = [
        _section_title("Sources & Provenance"),
        Paragraph(
            f"{n_calls} tool calls produced {n_unique} unique sources. "
            f"Every numerical claim in this memo traces back to one of these.",
            S["Small"],
        ),
        Spacer(1, 8),
    ]

    for t in sorted(by_type.keys(), key=lambda k: -len(by_type[k])):
        items = by_type[t]
        flowables.append(Paragraph(
            f"<font color='{INK_MUTED.hexval()}'><b>{type_labels.get(t, t.upper())}</b></font>"
            f"  <font color='{INK_GHOST.hexval()}'>·  {len(items)}</font>",
            S["Body"],
        ))
        for src in items[:8]:
            src_id = _escape(src.get("id") or "—")
            tool = _escape(src.get("tool") or "")
            form = src.get("form_type")
            tag = f"[{form}]" if form else ""
            url = src.get("url")
            line = (
                f"<font color='{INK_GHOST.hexval()}' face='Courier' size='7.5'>"
                f"{tool}</font>  "
                f"<font color='{INK.hexval()}' face='Courier' size='8'>{src_id}</font>  "
                f"<font color='{INK_GHOST.hexval()}' size='8'>{_escape(tag)}</font>"
            )
            if url:
                # "→" — keep glyph to one that Helvetica reliably renders.
                # The earlier "↗" rendered as a tofu box in some PDF viewers.
                line += (
                    f"  <font color='{ACCENT.hexval()}' size='7.5'>"
                    f"<link href='{_escape(url)}'>OPEN &#8594;</link></font>"
                )
            flowables.append(Paragraph(line, S["SourceItem"]))
        flowables.append(Spacer(1, 6))

    return flowables


def render_memo(memo: dict) -> bytes:
    """Render a single intelligence memo to PDF bytes.

    Layout:
      Page 1 (cover)  — band, KPI strip, big title, decision badge,
                        executive summary, key findings.
      Page 2+         — analysis prose, trade-idea cards, risk factor
                        blocks with severity bar, hedging, sources.

    The first page suppresses the small repeating header so the cover
    treatment can own the top of the page.
    """
    buf = io.BytesIO()
    title_text = memo.get("title") or memo.get("query", "Intelligence Memo")[:120]
    subtitle = (memo.get("query") or title_text)[:80]

    decision = (memo.get("decision") or "WATCH").upper()
    conf = int(memo.get("decision_confidence") or 0)
    macro_regime = (memo.get("macro_regime") or "").replace("_", " ").strip() or "—"
    risk_level = (memo.get("overall_risk_level") or "—").upper()
    created_at = (memo.get("created_at") or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    story: list = []

    # ── COVER ────────────────────────────────────────────────────
    story.append(_CoverBand(eyebrow="INTELLIGENCE MEMO", date_text=created_at, width=CONTENT_W))
    story.append(Spacer(1, 28))

    # Decision badge + KPI strip in a two-column header. Dropped DATE from
    # the strip — it's already prominent in the cover band, and three cards
    # gives each room to breathe without bumping the right page edge.
    # KPI strip width matches its column EXACTLY (not CONTENT_W) so the
    # rightmost card never hangs off the page.
    badge_w = 0.95 * inch
    badge = DecisionBadge(decision, width=badge_w, height=24)
    kpi_col_w = CONTENT_W - badge_w - 0.25 * inch
    kpi_items = [
        ("MACRO REGIME", macro_regime, INK),
        ("RISK LEVEL", risk_level,
            RED if "ELEVATED" in risk_level or "HIGH" in risk_level
            else YELLOW if "MODERATE" in risk_level
            else INK),
        ("CONVICTION", str(conf) if conf else "—", INK),
    ]
    cover_top = Table(
        [[badge, _kpi_strip(kpi_items, total_width=kpi_col_w)]],
        colWidths=[badge_w + 0.25 * inch, kpi_col_w],
    )
    cover_top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(cover_top)
    story.append(Spacer(1, 22))

    # Cover title
    story.append(Paragraph(_escape(title_text), S["CoverTitle"]))

    # Decision rationale, if present
    if memo.get("decision_reason"):
        story.append(Paragraph(_escape(memo["decision_reason"]), S["CoverSubtitle"]))

    # Executive summary — leads with the eyebrow + accent rule, like the
    # other sections so the reader gets one consistent rhythm.
    exec_sum = memo.get("executive_summary") or ""
    if exec_sum:
        story.append(_section_title("Executive Summary"))
        story.append(Paragraph(_escape(exec_sum), S["BodyJustified"]))

    # Key findings as a numbered list on the cover
    findings = memo.get("key_findings") or []
    if findings:
        story.append(_section_title("Key Findings"))
        for i, f in enumerate(findings[:8], 1):
            story.append(Paragraph(
                f"<font color='{ACCENT.hexval()}'><b>{i:02d}</b></font> &nbsp; {_escape(f)}",
                S["BulletItem"],
            ))

    # ── ANALYSIS ─────────────────────────────────────────────────
    analysis = memo.get("analysis") or ""
    if analysis:
        story.append(PageBreak())
        story.append(_section_title("Analysis"))
        for para in analysis.split("\n\n"):
            para = para.strip()
            if para:
                story.append(Paragraph(_escape(para), S["BodyJustified"]))

    # ── PLAN SHAPE ──────────────────────────────────────────────
    # The Interpreter's structural directives — what kind of question
    # this is, the benchmark, the target idea count, required style
    # coverage. Hidden when no plan-shape fields were emitted.
    plan_shape = _plan_shape_block(memo)
    if plan_shape:
        story.append(PageBreak())
        story.extend(plan_shape)

    # ── OPEN QUESTIONS ──────────────────────────────────────────
    # Sub-question coverage: which research questions the desk
    # actually addressed and which it didn't. Surfaces gaps the in-app
    # view shows as the `Q M/N` pill.
    open_q = _open_questions_block(memo)
    if open_q:
        story.extend(open_q)

    # ── WHAT WOULD CHANGE OUR VIEW ──────────────────────────────
    # Falsification criteria — bear cases scored low/medium/high. The
    # `[HIGH]` prefix tells the reader where to push back hardest.
    falsification = _falsification_block(memo)
    if falsification:
        story.extend(falsification)

    # ── TRADE IDEAS ─────────────────────────────────────────────
    # Split into CORE and SECONDARIES so non-mega-cap alpha names get
    # their own section. The numbering is global so #1 / #2 / #N stays
    # consistent between the two sections — readers always know which
    # idea is which regardless of how the split shakes out.
    trade_ideas = memo.get("trade_ideas") or []
    if trade_ideas:
        # Conviction distribution chart — drawn once over the full slate
        # so the reader sees the spread before drilling into individual
        # cards. Skipped when there are <2 ideas.
        chart = trade_idea_conviction_distribution(trade_ideas, width_pts=CONTENT_W)

        core_ideas: list[tuple[int, dict]] = []
        secondary_ideas: list[tuple[int, dict]] = []
        for i, idea in enumerate(trade_ideas[:12], 1):
            (secondary_ideas if _is_secondary_idea(idea) else core_ideas).append((i, idea))

        if core_ideas:
            story.append(PageBreak())
            story.append(_section_title(f"Trade Ideas  ·  {len(core_ideas)}  ·  Core"))
            if chart is not None:
                story.append(chart)
                story.append(Spacer(1, 10))
            for rank, idea in core_ideas:
                story.append(_trade_idea_card(idea, rank))

        if secondary_ideas:
            story.append(PageBreak())
            story.append(_section_title(
                f"Secondaries  ·  {len(secondary_ideas)}  ·  Alpha Sleeve · Mid / Small / Special"
            ))
            for rank, idea in secondary_ideas:
                story.append(_trade_idea_card(idea, rank))

    # ── REGIME SENSITIVITY ──────────────────────────────────────
    # Strategist's view of how positioning should shift across the four
    # macro regimes; current regime is starred.
    regime = _regime_sensitivity_block(memo)
    if regime:
        story.append(PageBreak())
        story.extend(regime)

    # ── RISK FACTORS ────────────────────────────────────────────
    risk_factors = memo.get("risk_factors") or []
    if risk_factors:
        story.append(PageBreak())
        story.append(_section_title("Risk Factors"))
        for rf in risk_factors[:12]:
            story.append(_risk_factor_block(rf))

    # ── HEDGING ─────────────────────────────────────────────────
    hedges = memo.get("hedging_recommendations") or []
    if hedges:
        story.append(_section_title("Hedging Recommendations"))
        for i, h in enumerate(hedges[:8], 1):
            story.append(Paragraph(
                f"<font color='{ACCENT.hexval()}'><b>H{i}</b></font> &nbsp; {_escape(h)}",
                S["BulletItem"],
            ))

    # ── MANDATE WARNINGS ────────────────────────────────────────
    mandate_warnings = memo.get("mandate_warnings") or []
    if mandate_warnings:
        story.append(_section_title("Mandate Check"))
        for w in mandate_warnings[:8]:
            story.append(Paragraph(
                f"<font color='{YELLOW.hexval()}'>▲</font>  {_escape(w)}",
                S["BulletItem"],
            ))

    # ── CITATIONS (numbered footnote index) ─────────────────────
    citations = _citation_index_block(memo)
    if citations:
        story.append(PageBreak())
        story.extend(citations)

    # ── SOURCES / PROVENANCE (tool-call lineage) ────────────────
    lineage = memo.get("lineage") or {}
    if lineage.get("sources"):
        # No PageBreak — flows naturally after the citation index when
        # both are present; if only sources exists, it gets its own page.
        if not citations:
            story.append(PageBreak())
        story.extend(_source_ledger(lineage))

    _build(
        buf, "Intelligence Memo", _trim_for_header(title_text), story,
        suppress_first_page_header=True,
    )
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
