"""Readable pure-Python PDF writer used when native renderers are unavailable."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("edocapi.processors.simple_pdf")


def _clean_text(value: str) -> str:
    """Normalize common DOCX typography while preserving meaningful content."""
    value = value.replace("\u00a0", " ").replace("\u00ad", "")
    value = value.replace("\u2010", "-").replace("\u2011", "-")
    value = value.replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "--")
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace("\u2026", "...")
    value = re.sub(r"[\t\v\f ]+", " ", value)
    return value.strip()


def text_to_pdf(
    text: str,
    *,
    temp_storage: Any = None,
    title: str = "Document",
    page_size: tuple[float, float] = (595.28, 841.89),
    margins: tuple[float, float, float, float] = (54.0, 54.0, 58.0, 52.0),
    paragraph_alignments: list[str] | None = None,
) -> Path:
    """Write readable, paginated text into a PDF using only the standard library.

    Supports lightweight Markdown conventions (headings, bullets, numbered
    lists, and tables) so structured DOCX fallbacks remain easy to scan.
    """
    page_width, page_height = page_size
    margin_x, margin_right, margin_top, margin_bottom = margins
    content_width = page_width - margin_x - margin_right
    body_size, body_leading = 10.5, 15.0
    max_chars = max(24, int(content_width / (body_size * 0.48)))

    def escape_pdf(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def wrap(value: str, width: int, font_size: float = body_size, bold: bool = False) -> list[str]:
        value = _clean_text(value)
        if not value:
            return [""]
        max_width = content_width if width == max_chars else content_width * width / max_chars
        words = value.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and _measure_text(candidate, font_size, bold) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
            while _measure_text(current, font_size, bold) > max_width and len(current) > 1:
                split_at = len(current) - 1
                while split_at > 1 and _measure_text(current[:split_at], font_size, bold) > max_width:
                    split_at -= 1
                lines.append(current[:split_at])
                current = current[split_at:]
        if current:
            lines.append(current)
        return lines or [""]

    # Each block is (kind, list of lines); paragraph boundaries are retained.
    blocks: list[tuple[str, list[str]]] = []
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        columns = max(len(row) for row in table_rows)
        column_width = max(8, (max_chars - 3 * (columns - 1)) // max(1, columns))
        for row in table_rows:
            cells = row + [""] * (columns - len(row))
            wrapped_cells = [wrap(cell, column_width, 9.0) for cell in cells]
            row_height = max(map(len, wrapped_cells))
            for line_index in range(row_height):
                rendered = [
                    (cell_lines[line_index] if line_index < len(cell_lines) else "").ljust(column_width)
                    for cell_lines in wrapped_cells
                ]
                blocks.append(("table", ["   ".join(rendered).rstrip()]))
            blocks.append(("table_space", []))
        table_rows = []

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            if raw.strip() == "__PAGE_BREAK__":
                flush_table()
                blocks.append(("pagebreak", []))
                continue
            flush_table()
            if blocks and blocks[-1][0] not in {"space", "table"}:
                blocks.append(("space", []))
            continue

        if "\t" in line:
            table_rows.append([_clean_text(cell) for cell in line.split("\t")])
            continue
        if " | " in line:
            table_rows.append([_clean_text(cell) for cell in line.split(" | ")])
            continue
        flush_table()

        if line == "__PAGE_BREAK__":
            blocks.append(("pagebreak", []))
            continue
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_size = {1: 17.0, 2: 13.5, 3: 11.5}[level]
            blocks.append((f"heading{level}", wrap(heading_match.group(2), max_chars, heading_size, True)))
            continue
        bullet_match = re.match(r"^(?:[-*\u2022]|(\d+)[.)])\s+(.+)$", line)
        if bullet_match:
            marker = f"{bullet_match.group(1)}." if bullet_match.group(1) else "-"
            content = bullet_match.group(2)
            lines = wrap(content, max_chars - 4)
            blocks.append(("list", [f"{marker} {lines[0]}"] + [f"   {part}" for part in lines[1:]]))
            continue
        blocks.append(("body", wrap(line, max_chars)))

    flush_table()
    while blocks and blocks[-1][0] == "space":
        blocks.pop()

    # Paginate and assign final coordinates together so spacing cannot drift.
    pages: list[list[tuple[str, str, float, float, tuple[float, float, float], bool, str]]] = [[]]
    y = page_height - margin_top
    available_bottom = margin_bottom + 18
    styles = {
        "heading1": (17.0, 23.0, (0.10, 0.23, 0.39), True),
        "heading2": (13.5, 19.0, (0.12, 0.31, 0.49), True),
        "heading3": (11.5, 16.5, (0.18, 0.34, 0.48), True),
        "body": (body_size, body_leading, (0.12, 0.14, 0.17), False),
        "list": (body_size, body_leading, (0.12, 0.14, 0.17), False),
        "table": (9.0, 13.0, (0.12, 0.14, 0.17), False),
        "table_space": (9.0, 5.0, (0.12, 0.14, 0.17), False),
        "space": (body_size, 7.0, (0.12, 0.14, 0.17), False),
        "pagebreak": (body_size, 0.0, (0.12, 0.14, 0.17), False),
    }

    alignment_index = 0
    for block_index, (kind, lines) in enumerate(blocks):
        if kind == "pagebreak":
            if pages[-1]:
                pages.append([])
            y = page_height - margin_top
            continue
        font_size, leading, _, _ = styles[kind]
        before = 8.0 if kind.startswith("heading") else (2.0 if kind == "body" else 0.0)
        after = 4.0 if kind.startswith("heading") else 1.0
        height = before + len(lines) * leading + after
        if kind.startswith("heading") and block_index + 1 < len(blocks):
            next_kind, next_lines = blocks[block_index + 1]
            if next_kind not in {"space"}:
                height += min(styles[next_kind][1], 16.0)
        # Keep headings with following text and avoid stranded last lines.
        if y - height < available_bottom and pages[-1]:
            pages.append([])
            y = page_height - margin_top
        y -= before
        align = "left"
        if kind == "body" and paragraph_alignments and alignment_index < len(paragraph_alignments):
            align = paragraph_alignments[alignment_index]
        if kind == "body":
            alignment_index += 1
        for line in lines:
            pages[-1].append((kind, line, y, font_size, styles[kind][2], styles[kind][3], align))
            y -= leading
        y -= after

    # Build PDF objects: catalog, page tree, Helvetica fonts, page/content pairs.
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [] /Count 0 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    page_ids: list[int] = []

    pages = [page for page in pages if page]
    if not pages:
        pages = [[]]
    for page_number, page_items in enumerate(pages, start=1):
        commands = ["q", "0.86 0.89 0.93 RG", "0.6 w", f"{margin_x} {page_height - 39} m {page_width - margin_x} {page_height - 39} l S", "Q"]
        commands += [
            "BT", "/F2 9 Tf", "0.18 0.28 0.40 rg",
            f"{margin_x} {page_height - 30} Td", f"({escape_pdf(_clean_text(title)[:72])}) Tj", "ET",
        ]
        for kind, line, y, font_size, color, bold, align in page_items:
            if kind in {"space", "table_space"}:
                continue
            font = "/F2" if bold else "/F1"
            r, g, b = color
            line_width = _measure_text(line, font_size, bold)
            if align == "center":
                x = margin_x + max(0.0, (content_width - line_width) / 2)
            elif align == "right":
                x = margin_x + max(0.0, content_width - line_width)
            else:
                x = margin_x
            commands.extend([
                "BT", f"{font} {font_size:g} Tf", f"{r:.3f} {g:.3f} {b:.3f} rg",
                f"{x:.2f} {y:.2f} Td", f"({escape_pdf(line)}) Tj", "ET",
            ])

        # Footer page number
        commands.extend([
            "BT", "/F1 8 Tf", "0.40 0.46 0.53 rg",
            f"{page_width - margin_right - 28:.2f} 28 Td", f"({page_number}) Tj", "ET",
        ])
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = len(objects) + 2
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.2f} {page_height:.2f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] "
        f"/Count {len(page_ids)} >>"
    ).encode()

    buffer = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, obj in enumerate(objects, start=1):
        offsets.append(len(buffer))
        buffer.extend(f"{object_number} 0 obj\n".encode())
        buffer.extend(obj)
        buffer.extend(b"\nendobj\n")
    xref_position = len(buffer)
    buffer.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    buffer.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.extend(f"{offset:010d} 00000 n \n".encode())
    buffer.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n".encode()
    )

    if temp_storage is not None:
        output = temp_storage.create_file(suffix=".pdf", prefix="simple_")
    else:
        import os
        import tempfile

        fd, name = tempfile.mkstemp(suffix=".pdf", prefix="simple_")
        os.close(fd)
        output = Path(name)
    output.write_bytes(bytes(buffer))
    return output


def structured_docx_to_pdf(processor: Any) -> Path:
    """Render DOCX paragraphs in order, retaining heading and table structure."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    lines: list[str] = []
    alignments: list[str] = []
    # Paragraphs and tables are emitted in document order, rather than moving
    # every table to the end of the report.
    body = processor._doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, processor._doc)
            if 'w:type="page"' in child.xml:
                lines.append("__PAGE_BREAK__")
            text = _clean_text(paragraph.text)
            if not text:
                continue
            style = paragraph.style.name.lower() if paragraph.style else ""
            if "heading 1" in style or style == "title":
                lines.append(f"# {text}")
            elif "heading 2" in style:
                lines.append(f"## {text}")
            elif "heading 3" in style or "heading" in style:
                lines.append(f"### {text}")
            elif "list bullet" in style:
                lines.append(f"- {text}")
            elif "list number" in style:
                lines.append(f"1. {text}")
            else:
                lines.append(text)
                alignment = paragraph.alignment
                alignments.append(
                    "center" if alignment == 1 else "right" if alignment == 2 else "left"
                )
            lines.append("")
        elif isinstance(child, CT_Tbl):
            table = Table(child, processor._doc)
            for row in table.rows:
                lines.append("\t".join(_clean_text(cell.text) for cell in row.cells))
            lines.append("")

    section = processor._doc.sections[0]
    page_size = (float(section.page_width.pt), float(section.page_height.pt))
    margins = (
        float(section.left_margin.pt),
        float(section.right_margin.pt),
        float(section.top_margin.pt),
        float(section.bottom_margin.pt),
    )
    title = processor._doc.core_properties.title or processor.path.stem.replace("_", " ")
    return text_to_pdf(
        "\n".join(lines),
        temp_storage=processor.temp_storage,
        title=title,
        page_size=page_size,
        margins=margins,
        paragraph_alignments=alignments,
    )


def _measure_text(text: str, font_size: float, bold: bool = False) -> float:
    """Approximate Helvetica glyph widths in PDF points to keep lines in bounds."""
    widths = {
        " ": 0.278, "!": 0.278, '"': 0.355, "#": 0.556, "$": 0.556, "%": 0.889,
        "&": 0.667, "'": 0.191, "(": 0.333, ")": 0.333, "*": 0.389, "+": 0.584,
        ",": 0.278, "-": 0.333, ".": 0.278, "/": 0.278, ":": 0.278, ";": 0.278,
        "<": 0.584, "=": 0.584, ">": 0.584, "?": 0.556, "@": 1.015,
        "[": 0.278, "\\": 0.278, "]": 0.278, "^": 0.469, "_": 0.556, "`": 0.333,
        "{": 0.334, "|": 0.260, "}": 0.334, "~": 0.584,
    }
    total = 0.0
    for char in text:
        if char in widths:
            total += widths[char]
        elif char.isdigit():
            total += 0.556
        elif char.isupper():
            total += 0.667 if char in "MW" else 0.667 if bold else 0.667
        else:
            total += 0.556 if bold else 0.5
    return total * font_size
