"""Markdown processor for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import markdown

from edocapi.exceptions import ConversionError
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi.processors.markdown")


@register_processor("markdown", "md")
class MarkdownProcessor(BaseProcessor):
    """Processor for Markdown documents."""

    supported_input_types = {"markdown", "md"}
    supported_output_types = {"pdf", "html", "txt"}

    def to_text(self) -> str:
        """Return the raw Markdown (or strip to plain text)."""
        return self.path.read_text(encoding="utf-8", errors="replace")

    def to_html(self) -> str:
        """Convert Markdown to HTML using the markdown library."""
        md = self.path.read_text(encoding="utf-8", errors="replace")
        html_body = markdown.markdown(
            md,
            extensions=["extra", "codehilite", "tables", "fenced_code"],
        )
        return f"<!DOCTYPE html><html><body>{html_body}</body></html>"

    def to_pdf(self) -> Path:
        """Markdown -> HTML -> PDF."""
        html = self.to_html()
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise ConversionError(
                "Markdown -> PDF requires weasyprint. "
                "Install with: pip install edocapi[html]",
                source="markdown",
                target="pdf",
            ) from exc

        storage = self.temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="md_")
        HTML(string=html).write_pdf(str(out))
        return out

    def info(self) -> dict[str, Any]:
        content = self.path.read_text(encoding="utf-8", errors="replace")
        return {
            "filename": self.path.name,
            "type": "markdown",
            "size": self.path.stat().st_size,
            "extension": self.path.suffix.lower(),
            "lines": content.count("\n") + 1,
        }
