"""Render the product testing lineup as a polished PDF using reportlab."""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT


GOLD = colors.HexColor("#C9A961")
INK = colors.HexColor("#1A1F26")
MUTED = colors.HexColor("#6E7681")
DIVIDER = colors.HexColor("#D0D7DE")
PALE = colors.HexColor("#F6F8FA")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20, leading=26, textColor=INK, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=MUTED, spaceAfter=18,
        ),
        "section_label": ParagraphStyle(
            "section_label", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=12, textColor=GOLD, spaceAfter=2,
            spaceBefore=4,
        ),
        "product_name": ParagraphStyle(
            "product_name", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=15, leading=20, textColor=INK, spaceAfter=2,
        ),
        "product_meta": ParagraphStyle(
            "product_meta", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=13, textColor=MUTED, spaceAfter=10,
        ),
        "field_label": ParagraphStyle(
            "field_label", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=11, textColor=MUTED, alignment=TA_LEFT,
        ),
        "field_value": ParagraphStyle(
            "field_value", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=INK,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=11, textColor=MUTED, alignment=TA_LEFT,
        ),
    }


def _escape(s: str | None) -> str:
    if not s:
        return "—"
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _product_card(p: dict, styles: dict) -> list:
    elements: list = []
    elements.append(Paragraph(
        f"<b>{_escape(p.get('product_name'))}</b>", styles["product_name"]
    ))
    meta_bits = []
    if p.get("brand_name"):
        meta_bits.append(f"Brand: <b>{_escape(p['brand_name'])}</b>")
    if p.get("niche"):
        meta_bits.append(f"Niche: {_escape(p['niche'])}")
    if p.get("date_added"):
        meta_bits.append(f"Date added: {_escape(p['date_added'])}")
    if p.get("status"):
        meta_bits.append(f"Status: <b>{_escape(p['status']).upper()}</b>")
    if p.get("hunted_by"):
        meta_bits.append(f"Hunted by: <b>{_escape(p['hunted_by'])}</b>")
    elements.append(Paragraph(" &nbsp;·&nbsp; ".join(meta_bits), styles["product_meta"]))

    field_rows = [
        ("MAIN PAIN POINT / DESIRE / PROBLEM", p.get("pain_point")),
        ("EMOTIONAL BENEFITS", p.get("emotional_benefits")),
        ("PHYSICAL EFFECTS", p.get("physical_effects")),
        ("MAIN INGREDIENTS", p.get("main_ingredients")),
    ]
    data = []
    for label, value in field_rows:
        data.append([
            Paragraph(label, styles["field_label"]),
            Paragraph(_escape(value), styles["field_value"]),
        ])

    # Target market section
    target_bits = []
    if p.get("target_age"):
        target_bits.append(f"<b>Age:</b> {_escape(p['target_age'])}")
    if p.get("target_gender"):
        target_bits.append(f"<b>Gender:</b> {_escape(p['target_gender'])}")
    if p.get("target_behavior"):
        target_bits.append(f"<b>Behavior:</b> {_escape(p['target_behavior'])}")
    if p.get("target_interest"):
        target_bits.append(f"<b>Interest:</b> {_escape(p['target_interest'])}")
    if p.get("target_demographics"):
        target_bits.append(f"<b>Demographics:</b> {_escape(p['target_demographics'])}")
    target_html = "<br/>".join(target_bits) if target_bits else "—"
    data.append([
        Paragraph("TARGET MARKET", styles["field_label"]),
        Paragraph(target_html, styles["field_value"]),
    ])

    if p.get("notes"):
        data.append([
            Paragraph("NOTES", styles["field_label"]),
            Paragraph(_escape(p["notes"]), styles["field_value"]),
        ])

    table = Table(data, colWidths=[55 * mm, 115 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, DIVIDER),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 8 * mm))
    return elements


def render_pdf(products: list[dict], title: str = "Product Testing Lineup") -> bytes:
    """Returns PDF bytes. Each product fits in a card layout, paginates automatically."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=title,
    )
    styles = _styles()
    flow: list = []

    flow.append(Paragraph(title, styles["title"]))
    flow.append(Paragraph(
        f"Generated {datetime.now().strftime('%B %d, %Y · %H:%M')} · "
        f"{len(products)} product{'s' if len(products) != 1 else ''}",
        styles["subtitle"],
    ))

    if not products:
        flow.append(Paragraph(
            "No products in the testing lineup yet.",
            styles["field_value"],
        ))
    else:
        for i, p in enumerate(products):
            flow.append(KeepTogether(_product_card(p, styles)))
            # Add page break after every 2 products to avoid overflow
            if (i + 1) % 2 == 0 and i < len(products) - 1:
                flow.append(PageBreak())

    def _on_page(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(2)
        canvas.line(18 * mm, 285 * mm, 60 * mm, 285 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(18 * mm, 12 * mm, "Orbit · Product Research · Testing Lineup")
        canvas.drawRightString(192 * mm, 12 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
