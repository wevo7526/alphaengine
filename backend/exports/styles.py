"""
Shared styles for Alpha Engine PDF exports.

Builds ReportLab ParagraphStyle + TableStyle objects that match the
platform's design system (dark-on-light for print, institutional feel).
"""

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import TableStyle

# ── Color palette (print-optimized, reflects UI dark theme semantics) ──
INK = colors.HexColor("#09090b")
INK_SOFT = colors.HexColor("#3f3f46")
INK_MUTED = colors.HexColor("#71717a")
INK_GHOST = colors.HexColor("#a1a1aa")
PAPER = colors.HexColor("#ffffff")
PAPER_SOFT = colors.HexColor("#fafafa")
DIVIDER = colors.HexColor("#e4e4e7")
ACCENT = colors.HexColor("#3b82f6")
GREEN = colors.HexColor("#059669")
RED = colors.HexColor("#dc2626")
YELLOW = colors.HexColor("#ca8a04")
ORANGE = colors.HexColor("#ea580c")


def build_styles():
    """Return dict of named ParagraphStyles used across all exports."""
    base = getSampleStyleSheet()

    s = {}
    s["Title"] = ParagraphStyle(
        "Title", parent=base["Heading1"],
        fontName="Helvetica-Bold", fontSize=18, leading=22,
        textColor=INK, spaceAfter=4,
    )
    s["Subtitle"] = ParagraphStyle(
        "Subtitle", parent=base["Normal"],
        fontName="Helvetica", fontSize=10, leading=13,
        textColor=INK_MUTED, spaceAfter=12,
    )
    s["SectionHeader"] = ParagraphStyle(
        "SectionHeader", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=9, leading=11,
        textColor=INK_MUTED, spaceBefore=16, spaceAfter=8,
        textTransform=None,
    )
    s["Body"] = ParagraphStyle(
        "Body", parent=base["Normal"],
        fontName="Helvetica", fontSize=10, leading=15,
        textColor=INK, spaceAfter=8, alignment=TA_LEFT,
    )
    s["BodyJustified"] = ParagraphStyle(
        "BodyJustified", parent=base["Normal"],
        fontName="Helvetica", fontSize=10, leading=15,
        textColor=INK, spaceAfter=10, alignment=TA_JUSTIFY,
    )
    s["Small"] = ParagraphStyle(
        "Small", parent=base["Normal"],
        fontName="Helvetica", fontSize=8.5, leading=12,
        textColor=INK_MUTED,
    )
    s["Mono"] = ParagraphStyle(
        "Mono", parent=base["Normal"],
        fontName="Courier", fontSize=9, leading=12,
        textColor=INK,
    )
    s["Badge"] = ParagraphStyle(
        "Badge", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=10, leading=14,
        textColor=colors.white, alignment=TA_CENTER,
    )
    s["BulletItem"] = ParagraphStyle(
        "BulletItem", parent=base["Normal"],
        fontName="Helvetica", fontSize=10, leading=14,
        textColor=INK, leftIndent=14, spaceAfter=4,
    )
    s["Quote"] = ParagraphStyle(
        "Quote", parent=base["Normal"],
        fontName="Helvetica-Oblique", fontSize=10, leading=14,
        textColor=INK_SOFT, leftIndent=12, rightIndent=12,
        spaceBefore=6, spaceAfter=10,
    )
    s["Footer"] = ParagraphStyle(
        "Footer", parent=base["Normal"],
        fontName="Helvetica", fontSize=7.5, leading=10,
        textColor=INK_GHOST, alignment=TA_CENTER,
    )
    s["H3"] = ParagraphStyle(
        "H3", parent=base["Heading3"],
        fontName="Helvetica-Bold", fontSize=11, leading=14,
        textColor=INK, spaceBefore=10, spaceAfter=6,
    )
    return s


# ── Table styles ──

def table_bordered_header():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PAPER_SOFT),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, DIVIDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, DIVIDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])


def table_statcards():
    """For the top-of-report summary cards (grid of stat boxes)."""
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, DIVIDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ])


def decision_color(decision: str) -> tuple:
    """Return (bg, fg) color tuple for a GO/NO-GO/WATCH badge."""
    d = (decision or "").upper()
    if d == "GO":
        return GREEN, colors.white
    if d == "NO-GO":
        return RED, colors.white
    return YELLOW, colors.white


def severity_color(severity: str) -> colors.Color:
    s = (severity or "").lower()
    if s == "critical":
        return RED
    if s == "high":
        return ORANGE
    if s == "medium":
        return YELLOW
    return INK_MUTED


def direction_color(direction: str) -> colors.Color:
    d = (direction or "").lower()
    if "bullish" in d:
        return GREEN
    if "bearish" in d:
        return RED
    return INK_MUTED


def pnl_color(pnl: float | None) -> colors.Color:
    if pnl is None:
        return INK_MUTED
    return GREEN if pnl >= 0 else RED
