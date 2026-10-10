"""Plain-text processor for eDocAPI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage


@register_processor("txt")
class TXTProcessor(BaseProcessor):
    """Processor for plain-text documents."""

    supported_input_types = {"txt"}
    supported_output_types = {"txt", "html", "pdf"}

    def to_text(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def to_html(self) -> str:
        text = (
            self.to_text()
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>\n")
        )
        return f"<html><body><pre>{text}</pre></body></html>"

    def to_pdf(self) -> Path:
        html = self.to_html()
        try:
            from weasyprint import HTML
        except (ImportError, OSError):
            HTML = None

        storage = self.temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="txt_")
        from edocapi.processors.simple_pdf import render_html_pdf, render_text_pdf

        text = self.to_text()
        if HTML is None:
            return render_text_pdf(text, out)
        return render_html_pdf(html, out, text)

    def info(self) -> dict[str, Any]:
        content = self.to_text()
        return {
            "filename": self.path.name,
            "type": "txt",
            "size": self.path.stat().st_size,
            "extension": ".txt",
            "lines": content.count("\n") + 1,
            "characters": len(content),
        }
