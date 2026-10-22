from __future__ import annotations

import io
import os
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#1677FF")
PALE_BLUE = colors.HexColor("#EAF3FF")
INK = colors.HexColor("#243B53")
MUTED = colors.HexColor("#627D98")
LINE = colors.HexColor("#D9E2EC")


def _register_unicode_font() -> str:
    candidates = (
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "Nirmala.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            try:
                pdfmetrics.registerFont(TTFont("ClassLensUnicode", candidate))
                return "ClassLensUnicode"
            except (OSError, ValueError):
                continue
    return "Helvetica"


def _safe_pdf_text(value: object, font_name: str) -> str:
    text = str(value)
    if font_name != "Helvetica":
        return escape(text).replace("\n", "<br/>")

    normalized = unicodedata.normalize("NFKD", text)
    safe_text = normalized.encode("cp1252", "replace").decode("cp1252")
    return escape(safe_text).replace("\n", "<br/>")


class _ScoreBar(Flowable):
    def __init__(self, score: int, width: float = 6.4 * inch, height: float = 15):
        super().__init__()
        self.score = score
        self.width = width
        self.height = height

    def draw(self) -> None:
        gap = 4
        segment_width = (self.width - gap * 4) / 5
        palette = ("#B7D7FF", "#83B9FF", "#529BFF", "#287FFF", "#145FE0")
        for index in range(5):
            x = index * (segment_width + gap)
            fill = colors.HexColor(palette[index]) if index < self.score else PALE_BLUE
            self.canv.setFillColor(fill)
            self.canv.roundRect(x, 3, segment_width, 9, 4.5, stroke=0, fill=1)


def _make_styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ClassLensTitle",
            parent=base["Title"],
            fontName=font_name,
            fontSize=24,
            leading=29,
            textColor=colors.white,
            alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "subtitle": ParagraphStyle(
            "ClassLensSubtitle",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#D7E9FF"),
        ),
        "section": ParagraphStyle(
            "ClassLensSection",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=14,
            leading=18,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ClassLensBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            textColor=INK,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "ClassLensSmall",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=8,
            leading=11,
            textColor=MUTED,
        ),
        "dimension": ParagraphStyle(
            "ClassLensDimension",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=10,
            leading=13,
            textColor=NAVY,
            spaceAfter=2,
        ),
        "badge": ParagraphStyle(
            "ClassLensBadge",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=16,
            leading=20,
            textColor=BLUE,
            alignment=TA_CENTER,
        ),
    }


def _paragraph(text: object, style: ParagraphStyle, font_name: str) -> Paragraph:
    return Paragraph(_safe_pdf_text(text, font_name), style)


def _rich_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _on_page(canvas, document) -> None:
    canvas.saveState()
    width, _ = letter
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(document.leftMargin, 0.55 * inch, width - document.rightMargin, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(document.leftMargin, 0.37 * inch, "ClassLens AI  |  AI-generated review; verify against the recording")
    canvas.drawRightString(width - document.rightMargin, 0.37 * inch, f"Page {document.page}")
    canvas.restoreState()


def _append_bullets(story: list, items: list[str], styles: dict[str, ParagraphStyle], font_name: str) -> None:
    if not items:
        story.append(_paragraph("None noted.", styles["small"], font_name))
        return
    for item in items:
        story.append(_paragraph(f"- {item}", styles["body"], font_name))


def build_assessment_pdf(report: dict) -> bytes:
    """Render a structured Gemini assessment as a shareable PDF."""
    font_name = _register_unicode_font()
    styles = _make_styles(font_name)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.8 * inch,
        title="ClassLens Class Review",
        author="ClassLens AI",
    )
    story = []

    title = _paragraph("CLASS REVIEW", styles["title"], font_name)
    subtitle = _paragraph("EVIDENCE-BASED VIDEO ASSESSMENT  |  GOOGLE GEMINI", styles["subtitle"], font_name)
    banner = Table([[title], [subtitle]], colWidths=[document.width])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, 0), 16),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 16),
    ]))
    story.extend([banner, Spacer(1, 12)])

    metadata = [
        [
            _rich_paragraph("<b>Recording</b>", styles["small"]),
            _paragraph(report.get("filename", "Uploaded class video"), styles["body"], font_name),
            _rich_paragraph("<b>Communication language</b>", styles["small"]),
            _rich_paragraph(
                f"{_safe_pdf_text(report.get('communication_language', 'Unclear'), font_name)} "
                f"(confidence: {_safe_pdf_text(report.get('language_confidence', 'Low'), font_name)})",
                styles["body"],
            ),
        ],
        [
            _rich_paragraph("<b>Overall rating</b>", styles["small"]),
            _rich_paragraph(
                f"{_safe_pdf_text(report['rating'], font_name)}  |  "
                f"{_safe_pdf_text(report.get('overall_score', 'N/A'), font_name)}/5",
                styles["badge"],
            ),
            _rich_paragraph("<b>Assessment confidence</b>", styles["small"]),
            _paragraph(report["confidence"], styles["body"], font_name),
        ],
    ]
    metadata_table = Table(metadata, colWidths=[1.15 * inch, 2.05 * inch, 1.35 * inch, 2.05 * inch])
    metadata_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([metadata_table, Spacer(1, 12)])

    story.append(_paragraph("Executive summary", styles["section"], font_name))
    story.append(_paragraph(report["summary"], styles["body"], font_name))
    if report.get("rating_method"):
        story.append(_paragraph(report["rating_method"], styles["small"], font_name))

    story.append(_paragraph("Dimension scores", styles["section"], font_name))
    for dimension in report["dimensions"]:
        score = dimension["score"]
        dimension_block = [
            _rich_paragraph(
                f"<b>{_safe_pdf_text(dimension['name'], font_name)}</b>"
                f"<font color='#1677FF'>  {score}/5</font>",
                styles["dimension"],
            ),
            _ScoreBar(score, document.width),
            _rich_paragraph(f"<b>Evidence:</b> {_safe_pdf_text(dimension['evidence'], font_name)}", styles["body"]),
            _rich_paragraph(f"<b>Limitation:</b> {_safe_pdf_text(dimension['limitation'], font_name)}", styles["small"]),
            Spacer(1, 7),
        ]
        story.append(KeepTogether(dimension_block))

    story.append(_paragraph("Strengths", styles["section"], font_name))
    _append_bullets(story, report["strengths"], styles, font_name)
    story.append(_paragraph("Improvement suggestions", styles["section"], font_name))
    _append_bullets(story, report["improvements"], styles, font_name)
    story.append(_paragraph("Technical observations and limitations", styles["section"], font_name))
    _append_bullets(story, report["limitations"], styles, font_name)

    story.append(Spacer(1, 10))
    story.append(_paragraph(
        "This AI-generated review may contain errors. Confirm names, observations, and conclusions against the original recording before sharing or acting on this report.",
        styles["small"],
        font_name,
    ))
    document.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()
