"""DOCX processor for eDocAPI (uses python-docx + weasyprint for PDF)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument

from edocapi.exceptions import ConversionError, InvalidDocument
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi.processors.docx")


@register_processor("docx")
class DOCXProcessor(BaseProcessor):
    """Processor for Microsoft Word (.docx) documents."""

    supported_input_types = {"docx"}
    supported_output_types = {"pdf", "txt", "html"}

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        super().__init__(path, temp_storage=temp_storage)
        try:
            self._doc = DocxDocument(str(path))
        except Exception as exc:
            raise InvalidDocument(f"Invalid or corrupted DOCX: {exc}") from exc

    def to_text(self) -> str:
        """Extract all paragraph text."""
        paragraphs = [p.text for p in self._doc.paragraphs if p.text.strip()]
        # Also extract tables
        for table in self._doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                paragraphs.append("\t".join(cells))
        return "\n".join(paragraphs)

    def to_html(self) -> str:
        """Convert DOCX to a simple HTML representation."""
        parts: list[str] = ["<html><body>"]
        for p in self._doc.paragraphs:
            style = p.style.name.lower() if p.style else ""
            text = (
                p.text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            if not text.strip():
                continue
            if "heading 1" in style:
                parts.append(f"<h1>{text}</h1>")
            elif "heading 2" in style:
                parts.append(f"<h2>{text}</h2>")
            elif "heading 3" in style:
                parts.append(f"<h3>{text}</h3>")
            else:
                parts.append(f"<p>{text}</p>")

        for table in self._doc.tables:
            parts.append("<table border='1'>")
            for row in table.rows:
                parts.append("<tr>")
                for cell in row.cells:
                    cell_text = (
                        cell.text.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    parts.append(f"<td>{cell_text}</td>")
                parts.append("</tr>")
            parts.append("</table>")

        parts.append("</body></html>")
        return "\n".join(parts)

    def to_pdf(self) -> Path:
        """Convert DOCX -> HTML -> PDF via WeasyPrint."""
        html = self.to_html()
        try:
            from weasyprint import HTML
        except (ImportError, OSError):
            HTML = None

        storage = self.temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="docx_")
        from edocapi.processors.simple_pdf import html_to_text, render_html_pdf, render_text_pdf

        fallback_text = self.to_text()
        if HTML is None:
            return render_text_pdf(fallback_text, out)
        return render_html_pdf(html, out, fallback_text or html_to_text(html))

    def info(self) -> dict[str, Any]:
        core = self._doc.core_properties
        return {
            "filename": self.path.name,
            "type": "docx",
            "size": self.path.stat().st_size,
            "extension": ".docx",
            "title": core.title or None,
            "author": core.author or None,
            "subject": core.subject or None,
            "created": str(core.created) if core.created else None,
            "modified": str(core.modified) if core.modified else None,
            "paragraphs": len(self._doc.paragraphs),
            "tables": len(self._doc.tables),
        }
