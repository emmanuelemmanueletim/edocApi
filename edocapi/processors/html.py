"""HTML processor for eDocAPI."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from edocapi.exceptions import ConversionError
from edocapi.processors.base import BaseProcessor, register_processor

logger = logging.getLogger("edocapi.processors.html")


@register_processor("html", "htm")
class HTMLProcessor(BaseProcessor):
    supported_input_types = {"html", "htm"}
    supported_output_types = {"pdf", "txt"}

    def to_text(self) -> str:
        content = self.path.read_text(encoding="utf-8", errors="replace")
        # Strip tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.I | re.S)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def to_pdf(self) -> Path:
        content = self.path.read_text(encoding="utf-8", errors="replace")
        try:
            from weasyprint import HTML
        except ImportError:
            from edocapi.processors.simple_pdf import text_to_pdf
            return text_to_pdf(self.to_text(), temp_storage=self.temp_storage)
        from edocapi.processors.safe_fetch import blocked_url_fetcher
        out = self._temp_path(suffix=".pdf", prefix="html_")
        try:
            HTML(string=content, url_fetcher=blocked_url_fetcher).write_pdf(str(out))
            return out
        except Exception as exc:
            self._discard_temp(out)
            raise ConversionError("HTML to PDF conversion failed.") from exc

    def info(self) -> dict[str, Any]:
        base = super().info()
        content = self.path.read_text(encoding="utf-8", errors="replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
        base["title"] = title_match.group(1).strip() if title_match else ""
        return base
