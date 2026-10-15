"""Markdown processor for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import markdown as md_lib

from edocapi.exceptions import ConversionError
from edocapi.processors.base import BaseProcessor, register_processor

logger = logging.getLogger("edocapi.processors.markdown")


@register_processor("markdown", "md")
class MarkdownProcessor(BaseProcessor):
    supported_input_types = {"markdown", "md"}
    supported_output_types = {"pdf", "html", "txt"}

    def to_text(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def to_html(self) -> str:
        text = self.to_text()
        body = md_lib.markdown(text, extensions=["extra", "tables", "fenced_code"])
        return f'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>{body}</body></html>'

    def to_pdf(self) -> Path:
        html = self.to_html()
        try:
            from weasyprint import HTML
            out = self._temp_path(suffix=".pdf", prefix="md_")
            HTML(string=html).write_pdf(str(out))
            return out
        except Exception as exc:
            logger.info("WeasyPrint unavailable (%s) - falling back to simple PDF", exc)
            from edocapi.processors.simple_pdf import text_to_pdf
            return text_to_pdf(self.to_text(), temp_storage=self.temp_storage)

    def info(self) -> dict[str, Any]:
        base = super().info()
        text = self.to_text()
        base["lines"] = text.count("\n") + 1
        base["chars"] = len(text)
        return base
