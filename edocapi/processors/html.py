"""HTML processor for eDocAPI (uses weasyprint for PDF)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from edocapi.exceptions import ConversionError
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi.processors.html")


@register_processor("html")
class HTMLProcessor(BaseProcessor):
    """Processor for HTML documents."""

    supported_input_types = {"html"}
    supported_output_types = {"pdf", "txt", "html"}

    def to_text(self) -> str:
        """Strip tags and return approximate plain text."""
        content = self.path.read_text(encoding="utf-8", errors="replace")
        # Very simple tag stripping
        text = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def to_html(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def to_pdf(self) -> Path:
        """Convert HTML to PDF using WeasyPrint."""
        try:
            from weasyprint import HTML
        except (ImportError, OSError):
            HTML = None

        storage = self.temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="html_")
        from edocapi.processors.simple_pdf import html_to_text, render_html_pdf, render_text_pdf

        source = self.path.read_text(encoding="utf-8", errors="replace")
        text = html_to_text(source)
        if HTML is None:
            return render_text_pdf(text, out)
        return render_html_pdf(source, out, text)

    def info(self) -> dict[str, Any]:
        content = self.path.read_text(encoding="utf-8", errors="replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.DOTALL)
        title = title_match.group(1).strip() if title_match else None
        return {
            "filename": self.path.name,
            "type": "html",
            "size": self.path.stat().st_size,
            "extension": self.path.suffix.lower(),
            "title": title,
        }
