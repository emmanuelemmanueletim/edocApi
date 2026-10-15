"""Plain-text processor for eDocAPI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edocapi.processors.base import BaseProcessor, register_processor


@register_processor("txt")
class TxtProcessor(BaseProcessor):
    supported_input_types = {"txt"}
    supported_output_types = {"pdf", "txt", "html"}

    def to_text(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def to_html(self) -> str:
        import html as html_mod
        text = html_mod.escape(self.to_text())
        paragraphs = "".join(f"<p>{p}</p>" for p in text.split("\n\n") if p.strip())
        return f'<!DOCTYPE html><html><body>{paragraphs}</body></html>'

    def to_pdf(self) -> Path:
        from edocapi.processors.simple_pdf import text_to_pdf
        return text_to_pdf(self.to_text(), temp_storage=self.temp_storage)

    def info(self) -> dict[str, Any]:
        base = super().info()
        text = self.to_text()
        base["lines"] = text.count("\n") + 1
        base["chars"] = len(text)
        return base
