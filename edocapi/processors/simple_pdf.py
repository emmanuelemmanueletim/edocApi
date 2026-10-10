"""Pillow-based PDF fallback for text documents when WeasyPrint is unavailable."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


class _TextExtractor(HTMLParser):
    _BLOCKS = {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p",
        "pre", "section", "table", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "head"):
            self._hidden += 1
        elif not self._hidden and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head") and self._hidden:
            self._hidden -= 1
        elif not self._hidden and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_to_text(source: str) -> str:
    parser = _TextExtractor()
    parser.feed(source)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def render_text_pdf(text: str, output: Path) -> Path:
    """Render readable, paginated text into a PDF using Pillow's PDF writer."""
    page_width, page_height = 850, 1100
    margin_x, margin_y = 58, 62
    font = _load_font(18)
    line_height = 26
    max_width = page_width - 2 * margin_x
    pages: list[Image.Image] = []
    page = _new_page(page_width, page_height)
    draw = ImageDraw.Draw(page)
    y = margin_y

    for paragraph in (text or "(No extractable text in this document.)").splitlines() or [""]:
        words = paragraph.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if not lines:
            lines = [""]
        for line in lines:
            if y + line_height > page_height - margin_y:
                pages.append(page)
                page = _new_page(page_width, page_height)
                draw = ImageDraw.Draw(page)
                y = margin_y
            draw.text((margin_x, y), line, fill="#17211b", font=font)
            y += line_height
        y += 10

    pages.append(page)
    pages[0].save(
        output,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=110.0,
    )
    return output


def render_html_pdf(html: str, output: Path, fallback_text: str) -> Path:
    """Prefer WeasyPrint; use a self-contained Pillow renderer if GTK is absent."""
    try:
        from weasyprint import HTML
    except ImportError:
        return render_text_pdf(fallback_text, output)

    try:
        HTML(string=html).write_pdf(str(output))
        return output
    except Exception as exc:
        message = str(exc).lower()
        if "libgobject" in message or "cannot load library" in message:
            return render_text_pdf(fallback_text, output)
        raise


def _new_page(width: int, height: int) -> Image.Image:
    return Image.new("RGB", (width, height), "white")


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                pass
    return ImageFont.load_default()
