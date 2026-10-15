"""High-quality DOCX to PDF rendering with ReportLab's flow layout engine."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

logger = logging.getLogger("edocapi.processors.docx_reportlab")

_ALIGNMENTS = {
    0: TA_LEFT,
    1: TA_CENTER,
    2: TA_RIGHT,
    3: TA_JUSTIFY,
}


def _escape_run_text(text: str) -> str:
    """Escape DOCX run text for ReportLab Paragraph's XML-like markup."""
    return html.escape(text, quote=False).replace("\n", "<br/>")


def _paragraph_markup(paragraph: Any, *, preserve_color: bool = True) -> str:
    chunks: list[str] = []
    for run in paragraph.runs:
        text = _escape_run_text(run.text)
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        if run.underline:
            text = f"<u>{text}</u>"
        if run.font.size is not None:
            text = f'<font size="{run.font.size.pt:g}">{text}</font>'
        if preserve_color and run.font.color and run.font.color.rgb:
            text = f'<font color="#{run.font.color.rgb}">{text}</font>'
        chunks.append(text)
    if chunks:
        return "".join(chunks)
    return _escape_run_text(paragraph.text)


def _make_styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "ReportBody",
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#263445"),
        spaceBefore=1.5 * mm,
        spaceAfter=3 * mm,
        alignment=TA_JUSTIFY,
        allowWidows=0,
        allowOrphans=0,
        splitLongWords=1,
    )
    return {
        "body": body,
        "title": ParagraphStyle(
            "ReportTitle", parent=body, fontName="Helvetica-Bold", fontSize=22,
            leading=27, alignment=TA_CENTER, textColor=colors.HexColor("#17365D"),
            spaceBefore=8 * mm, spaceAfter=5 * mm, keepWithNext=True,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", parent=body, fontName="Helvetica", fontSize=12,
            leading=17, alignment=TA_CENTER, textColor=colors.HexColor("#526579"),
            spaceAfter=7 * mm, keepWithNext=True,
        ),
        "caption": ParagraphStyle(
            "ReportCaption", parent=body, fontName="Helvetica-Oblique", fontSize=9,
            leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#526579"),
            spaceBefore=1.5 * mm, spaceAfter=3 * mm, keepWithNext=True,
        ),
        "toc": ParagraphStyle(
            "ReportTOC", parent=body, fontName="Helvetica-Bold", fontSize=10,
            leading=16.5, textColor=colors.HexColor("#263F59"),
            alignment=TA_LEFT, leftIndent=2 * mm, spaceBefore=0, spaceAfter=2 * mm,
        ),
        "toc_sub": ParagraphStyle(
            "ReportTOCSub", parent=body, fontSize=9.5, leading=15,
            alignment=TA_LEFT, leftIndent=10 * mm, spaceBefore=0, spaceAfter=1.5 * mm,
            textColor=colors.HexColor("#526579"),
        ),
        "heading1": ParagraphStyle(
            "ReportHeading1", parent=body, fontName="Helvetica-Bold", fontSize=16,
            leading=20, alignment=TA_LEFT, textColor=colors.HexColor("#17365D"),
            spaceBefore=7 * mm, spaceAfter=3 * mm, keepWithNext=True,
        ),
        "heading2": ParagraphStyle(
            "ReportHeading2", parent=body, fontName="Helvetica-Bold", fontSize=13,
            leading=17, alignment=TA_LEFT, textColor=colors.HexColor("#24527A"),
            spaceBefore=5 * mm, spaceAfter=2 * mm, keepWithNext=True,
        ),
        "heading3": ParagraphStyle(
            "ReportHeading3", parent=body, fontName="Helvetica-Bold", fontSize=11,
            leading=15, alignment=TA_LEFT, textColor=colors.HexColor("#344B62"),
            spaceBefore=4 * mm, spaceAfter=1.5 * mm, keepWithNext=True,
        ),
        "list": ParagraphStyle(
            "ReportList", parent=body, alignment=TA_LEFT, leftIndent=7 * mm,
            firstLineIndent=-4 * mm, spaceBefore=0, spaceAfter=1.5 * mm,
        ),
        "table": ParagraphStyle(
            "ReportTableCell", parent=body, fontSize=8.5, leading=11,
            alignment=TA_LEFT, spaceBefore=0, spaceAfter=0,
            textColor=colors.HexColor("#263445"),
        ),
        "table_header": ParagraphStyle(
            "ReportTableHeader", parent=body, fontName="Helvetica-Bold",
            fontSize=8.5, leading=11, alignment=TA_LEFT, spaceBefore=0,
            spaceAfter=0, textColor=colors.HexColor("#17365D"),
        ),
        "table_label": ParagraphStyle(
            "ReportTableLabel", parent=body, fontName="Helvetica-Bold",
            fontSize=8.5, leading=11, alignment=TA_LEFT, spaceBefore=0,
            spaceAfter=0, textColor=colors.HexColor("#263445"),
        ),
    }


def _style_name(paragraph: Any) -> str:
    return (paragraph.style.name if paragraph.style else "Normal").strip().lower()


def _paragraph_style_key(paragraph: Any, *, in_toc: bool = False) -> str:
    name = _style_name(paragraph)
    text = paragraph.text.strip()
    if text.lower() == "table of contents":
        return "heading1"
    if text.startswith("Table ") and "." in text[:12]:
        return "caption"
    if name == "title":
        return "title"
    if name.startswith("subtitle"):
        return "subtitle"
    if name.startswith("heading 1") or name in {"heading", "chapter title"}:
        return "heading1"
    if name.startswith("heading 2"):
        return "heading2"
    if name.startswith("heading 3") or name.startswith("heading"):
        return "heading3"
    if in_toc and re.match(r"^\d+(?:\.\d+){1,2}\s+", text):
        return "toc_sub"
    if in_toc and re.match(r"^\d+\.\s+", text):
        return "toc"
    # Many Word cover pages use direct run formatting instead of a named style.
    # Retain those titles and subtitles when the DOCX is rendered to PDF.
    alignment = paragraph.alignment
    run_sizes = [run.font.size.pt for run in paragraph.runs if run.font.size is not None]
    if alignment == 1 and run_sizes:
        if max(run_sizes) >= 15:
            return "title"
        if max(run_sizes) >= 10.5:
            return "subtitle"
    if "list bullet" in name or "list number" in name or "list paragraph" in name:
        return "list"
    return "body"


def _paragraph_flowable(
    paragraph: Any,
    styles: dict[str, ParagraphStyle],
    *,
    in_toc: bool = False,
) -> Any:
    key = _paragraph_style_key(paragraph, in_toc=in_toc)
    style = styles[key]
    alignment = paragraph.alignment
    if alignment is not None and key not in {"title", "subtitle", "caption", "heading1", "heading2", "heading3"}:
        style = ParagraphStyle(
            f"{style.name}Aligned{int(alignment)}",
            parent=style,
            alignment=_ALIGNMENTS.get(int(alignment), TA_LEFT),
        )
    markup = _paragraph_markup(paragraph)
    if key == "list":
        markup = f"- {markup}"
    return Paragraph(markup, style)


def _table_flowable(table: Any, styles: dict[str, ParagraphStyle], available_width: float) -> LongTable:
    rows: list[list[Paragraph]] = []
    column_count = max((len(row.cells) for row in table.rows), default=1)
    # Use the source table's grid when it is available so label columns and
    # wider description columns retain their intended proportions.
    source_widths = []
    for column in list(table.columns)[:column_count]:
        width = getattr(column, "width", None)
        source_widths.append(float(width.pt) if width is not None else 0.0)
    if len(source_widths) < column_count:
        source_widths.extend([0.0] * (column_count - len(source_widths)))
    width_total = sum(source_widths)
    if width_total > 0 and all(width > 0 for width in source_widths):
        col_widths = [available_width * width / width_total for width in source_widths]
    else:
        col_widths = [available_width / max(column_count, 1)] * column_count
    for row_index, row in enumerate(table.rows):
        rendered_row: list[Paragraph] = []
        for column_index, cell in enumerate(row.cells):
            cell_text = "<br/>".join(
                _paragraph_markup(paragraph, preserve_color=False)
                for paragraph in cell.paragraphs if paragraph.text.strip()
            ) or "&#160;"
            cell_style = (
                styles["table_header"] if row_index == 0
                else styles["table_label"] if column_index == 0
                else styles["table"]
            )
            rendered_row.append(Paragraph(cell_text, cell_style))
        rendered_row.extend(
            Paragraph("&#160;", styles["table"])
            for _ in range(column_count - len(rendered_row))
        )
        rows.append(rendered_row)

    flowable = LongTable(
        rows,
        colWidths=col_widths,
        repeatRows=1 if len(rows) > 1 else 0,
        hAlign="LEFT",
        splitByRow=1,
    )
    flowable.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1F8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#A9B8C8")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#71869B")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F0F4F8")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#263445")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17365D")),
    ]))
    return flowable


def _page_chrome(title: str):
    def draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        width, height = doc.pagesize
        canvas.setStrokeColor(colors.HexColor("#D8E0E8"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, height - 13 * mm, width - doc.rightMargin, height - 13 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#617386"))
        canvas.drawString(doc.leftMargin, height - 10 * mm, title[:100])
        canvas.line(doc.leftMargin, 12 * mm, width - doc.rightMargin, 12 * mm)
        canvas.drawRightString(width - doc.rightMargin, 8 * mm, f"{doc.page}")
        canvas.restoreState()
    return draw


def convert_docx_with_reportlab(processor: Any, output: Path) -> Path:
    """Render DOCX paragraphs and tables as paginated, styled PDF flowables."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    document = processor._doc
    section = document.sections[0]
    page_size = (float(section.page_width.pt), float(section.page_height.pt))
    left = float(section.left_margin.pt)
    right = float(section.right_margin.pt)
    top = max(float(section.top_margin.pt), 20 * mm)
    bottom = max(float(section.bottom_margin.pt), 18 * mm)
    title = document.core_properties.title or processor.path.stem.replace("_", " ")
    styles = _make_styles()
    story: list[Any] = []
    body = document.element.body
    in_toc = False
    saw_cover_title = False
    cover_break_inserted = False

    for child in body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = DocxParagraph(child, document)
            text = paragraph.text.strip()
            style_name = _style_name(paragraph)
            is_toc_title = text.lower() == "table of contents"
            is_heading1 = style_name.startswith("heading 1") or style_name in {"heading", "chapter title"}
            is_cover_title = _paragraph_style_key(paragraph) == "title"
            page_break_before = paragraph.paragraph_format.page_break_before
            start_main_sections = (
                saw_cover_title and not cover_break_inserted and is_heading1 and not is_toc_title
            )
            if (
                page_break_before
                or 'w:type="page"' in child.xml
                or start_main_sections
                or is_toc_title
                or (in_toc and is_heading1)
            ):
                story.append(PageBreak())
            if start_main_sections:
                cover_break_inserted = True
            if not text:
                continue
            if in_toc and not is_toc_title and style_name.startswith("heading 1"):
                in_toc = False
            flowable = _paragraph_flowable(paragraph, styles, in_toc=in_toc)
            # Keep titles and headings attached to the following paragraph.
            if _paragraph_style_key(paragraph, in_toc=in_toc) in {"title", "subtitle", "heading1", "heading2", "heading3"}:
                story.append(KeepTogether([flowable, Spacer(1, 0.5)]))
            else:
                story.append(flowable)
            if is_toc_title:
                in_toc = True
            if is_cover_title:
                saw_cover_title = True
        elif isinstance(child, CT_Tbl):
            docx_table = DocxTable(child, document)
            available_width = page_size[0] - left - right
            story.append(_table_flowable(docx_table, styles, available_width))
            story.append(Spacer(1, 4 * mm))

    if not story:
        story.append(Paragraph("(This document contains no readable text.)", styles["body"]))

    template = SimpleDocTemplate(
        str(output),
        pagesize=page_size or A4,
        leftMargin=left,
        rightMargin=right,
        topMargin=top,
        bottomMargin=bottom,
        title=title,
        author=document.core_properties.author or "",
        subject=document.core_properties.subject or "",
    )
    chrome = _page_chrome(title)
    template.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return output


def new_output_path(processor: Any) -> Path:
    return processor._temp_path(suffix=".pdf", prefix="docx_report_")
