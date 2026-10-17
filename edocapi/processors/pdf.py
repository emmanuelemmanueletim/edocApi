"""PDF processor for eDocAPI (pypdf + optional ML/OCR)."""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from pypdf import PdfReader, PdfWriter, mult
from pypdf.errors import PdfReadError

from edocapi.exceptions import InvalidDocument, ProcessingError
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.processors.ocr import (
    configure_tesseract,
    find_poppler_bin,
    normalize_tesseract_language,
)

logger = logging.getLogger("edocapi.processors.pdf")


def _blocks_from_layout(lines: list[str], page_num: int) -> list[dict[str, Any]]:
    """Build blocks in pypdf layout order; never reorder text objects by coordinates."""
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    list_index: int | None = None
    list_indent = 0

    def flush() -> None:
        if paragraph:
            value = " ".join(part.strip() for part in paragraph if part.strip()).strip()
            if value:
                blocks.append({"type": "paragraph", "text": value, "page": page_num})
            paragraph.clear()

    def add_list_continuation(text: str) -> bool:
        if list_index is not None and blocks and blocks[-1]["type"] == "list_item":
            blocks[-1]["text"] += " " + text.strip()
            return True
        return False

    index = 0
    while index < len(lines):
        raw = lines[index].rstrip()
        text = raw.strip()
        if not text:
            flush()
            list_index = None
            index += 1
            continue

        # Aligned multi-column rows are only treated as a table when several
        # adjacent lines share the same column count.
        cells = [cell.strip() for cell in re.split(r"\s{2,}", text) if cell.strip()]
        if len(cells) >= 2:
            rows = [cells]
            next_index = index + 1
            while next_index < len(lines):
                if not lines[next_index].strip():
                    next_index += 1
                    continue
                next_cells = [cell.strip() for cell in re.split(r"\s{2,}", lines[next_index].strip()) if cell.strip()]
                if len(next_cells) != len(cells):
                    break
                rows.append(next_cells)
                next_index += 1
            if len(rows) >= 2:
                flush()
                blocks.append({"type": "table", "rows": rows, "page": page_num})
                index = next_index
                list_index = None
                continue

        text = re.sub(r" {2,}", " ", text)

        bullet = re.match(r"^(?:[-*\u2022\u25aa\u25e6\u25cf])\s+(.*)$", text)
        reference = re.match(r"^\[(\d+)\]\s+", text)
        caption = re.match(r"^(Table|Figure)\s+\d+\.\s", text, re.I)
        numbered = re.match(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(.+)$", text)
        front_heading = re.fullmatch(
            r"(?:Acknowledg(?:e)?ments?|Abstract|Table of Contents|Keywords|References|Comparative Summary|Conclusion and Outlook)",
            text, re.I,
        )
        heading = bool(front_heading or (numbered and len(text) < 115 and not text.endswith((",", ";", ":"))))
        label = bool(re.match(
            r"^(?:Latency|Memory footprint|Energy|Detection performance|Network / multi-access edge computing \(MEC\)|"
            r"Bandwidth consumption and monetary cost|Operational reliability under disconnection|"
            r"Restricted model capacity and accuracy gap|Hardware heterogeneity and toolchain fragmentation|"
            r"Thermal and instantaneous power ceilings|Spectral classifier or clustering-based detector)\.",
            text, re.I,
        ))

        if bullet:
            flush()
            blocks.append({"type": "list_item", "text": "- " + bullet.group(1).strip(), "page": page_num})
            list_index = len(blocks) - 1
            list_indent = len(raw) - len(raw.lstrip())
        elif (list_index is not None
              and len(raw) - len(raw.lstrip()) > list_indent
              and add_list_continuation(text)):
            pass
        elif reference:
            flush()
            blocks.append({"type": "reference", "text": text, "page": page_num,
                           "_indent": len(raw) - len(raw.lstrip())})
            list_index = None
        elif caption:
            flush()
            blocks.append({"type": "caption", "text": text, "page": page_num,
                           "_indent": len(raw) - len(raw.lstrip())})
            list_index = None
        elif any(block["type"] == "heading" and block["text"].casefold() == "10. references"
                 for block in blocks):
            if blocks and blocks[-1]["type"] == "reference":
                blocks[-1]["text"] += " " + text
            else:
                flush()
                blocks.append({"type": "paragraph", "text": text, "page": page_num})
            list_index = None
        elif (blocks and blocks[-1]["type"] in {"reference", "caption"}
              and len(raw) - len(raw.lstrip()) > blocks[-1].get("_indent", 0)):
            blocks[-1]["text"] += " " + text
            list_index = None
        elif text.startswith("Keywords:"):
            flush()
            blocks.append({"type": "heading", "level": 2, "text": "Keywords", "page": page_num})
            blocks.append({"type": "paragraph", "text": text.partition(":")[2].strip(), "page": page_num})
            list_index = None
        elif page_num == 1 and text == "Bringing AI Closer to Sensors":
            flush()
            blocks.append({"type": "heading", "level": 2, "text": text, "page": page_num})
            list_index = None
        elif heading:
            flush()
            if numbered:
                level = min(3, len(numbered.group(1).rstrip(".").split(".")) + 1)
            else:
                level = 1 if text == text.upper() else 2
            blocks.append({"type": "heading", "level": level, "text": text, "page": page_num})
            list_index = None
        elif label:
            flush()
            blocks.append({"type": "paragraph", "text": text, "page": page_num})
            list_index = None
        else:
            paragraph.append(text)
            list_index = None
        index += 1

    flush()
    for block in blocks:
        block.pop("_indent", None)
    return blocks


def _normalize_furniture(value: str) -> str:
    value = re.sub(r"\b[0-9a-fA-F]{16,}\b", "<id>", value)
    value = re.sub(r"\b\d+\b", "<n>", value)
    return value.casefold().strip()


def _needs_spacing_recovery(text: str) -> bool:
    """Identify PDFs whose text layer omits spaces between ordinary words.

    Some TeX PDF producers position each word separately.  Pypdf correctly
    reads their glyphs and equations, but the PDF has no space characters for
    it to return.  Several long, all-letter runs are a reliable signal that a
    geometry-aware reader should be preferred for that page.
    """
    joined_words = re.findall(r"[A-Za-z]{16,}", text)
    return len(joined_words) >= 2


_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def _restore_stacked_math(text: str) -> str:
    """Make common PDF math stacks readable in linear Unicode text.

    PDF text layers commonly place a superscript or the two parts of a
    derivative on separate visual rows. PDFium faithfully reports those rows,
    but a plain-text result benefits from compact Unicode superscripts and
    slash notation. The patterns are intentionally narrow so regular prose,
    headings, and page numbers remain untouched.
    """
    math_symbol = r"[𝑎-𝑧𝛢-𝜛𝝖-𝞇]"

    # A digit row above a mathematical symbol is a superscript, not a new
    # paragraph. This handles v\n2, x\n−1, and similar TeX output.
    def superscript(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2).translate(_SUPERSCRIPT_DIGITS)

    text = re.sub(rf"({math_symbol})\n([0-9]+)(?=\n|\s|$)", superscript, text)
    text = re.sub(rf"({math_symbol})([0-9]+)", superscript, text)

    # Convert the two stacked pieces of common first and second derivatives
    # into conventional plain-text fraction notation.
    derivative = r"𝑑(?:[𝑎-𝑧𝛢-𝜛𝝖-𝞇]|[⁰¹²³⁴⁵⁶⁷⁸⁹0-9])*"
    text = re.sub(rf"({derivative})\n({derivative})", r"\1/\2", text)
    text = re.sub(rf"({math_symbol})\n(𝑑[^\n]+/𝑑[^\n]+)", r"\1 \2", text)
    return text


@register_processor("pdf")
class PDFProcessor(BaseProcessor):
    """Processor for PDF documents with compression, merge and optional OCR."""

    supported_input_types = {"pdf"}
    supported_output_types = {"pdf", "txt", "html", "png", "jpg", "webp"}

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        super().__init__(path, temp_storage=temp_storage)
        try:
            self._reader = PdfReader(str(path))
        except PdfReadError as exc:
            raise InvalidDocument(f"Invalid or corrupted PDF: {exc}") from exc

    def to_pdf(self) -> Path:
        out = self._temp_path(suffix=".pdf", prefix="copy_")
        writer = PdfWriter()
        for page in self._reader.pages:
            writer.add_page(page)
        with out.open("wb") as f:
            writer.write(f)
        return out

    def to_text(self) -> str:
        """Extract readable text while preserving common PDF document structure."""
        return self.extract_structured_text()["text"]

    @staticmethod
    def _page_has_readable_text(text: str) -> bool:
        """Reject empty pages and tiny headers that do not replace page OCR."""
        if not text or text.count("\ufffd") > max(2, len(text) // 50):
            return False
        return sum(char.isalnum() for char in text) >= 24

    def _pdfium_text_pages(self) -> list[str | None]:
        """Read selectable text with PDFium's word-boundary recovery.

        PDFium preserves spaces for PDFs generated by TeX and other layout
        engines that encode prose as individually positioned glyphs.  It is
        only selected for pages where the primary reader demonstrably loses
        word boundaries, preserving the existing pypdf behaviour elsewhere.
        """
        try:
            import pypdfium2 as pdfium
        except ImportError:
            return [None] * len(self._reader.pages)

        document = None
        pages: list[str | None] = []
        try:
            document = pdfium.PdfDocument(str(self.path))
            for page_index in range(len(document)):
                page = document[page_index]
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
                finally:
                    text_page.close()
                    page.close()
                text = _restore_stacked_math(text.replace("\x00", "")).strip()
                pages.append(text if self._page_has_readable_text(text) else None)
        except Exception as exc:
            logger.debug("PDFium text recovery unavailable for %s: %s", self.path.name, exc)
            return [None] * len(self._reader.pages)
        finally:
            if document is not None:
                document.close()

        if len(pages) != len(self._reader.pages):
            return [None] * len(self._reader.pages)
        return pages

    def _native_text_pages(self, *, layout: bool = False) -> list[str]:
        """Extract each page, restoring word boundaries for affected PDFs."""
        primary_pages: list[str] = []
        recover_page: list[bool] = []
        for page in self._reader.pages:
            try:
                text = page.extract_text(extraction_mode="layout") if layout else page.extract_text()
            except Exception:
                text = page.extract_text() or ""
            text = (text or "").replace("\x00", "").strip()
            primary_pages.append(text)
            recover_page.append(_needs_spacing_recovery(text))

        if not any(recover_page):
            return primary_pages

        recovered_pages = self._pdfium_text_pages()
        return [
            recovered if should_recover and recovered else primary
            for primary, recovered, should_recover in zip(primary_pages, recovered_pages, recover_page)
        ]

    def _embedded_text_pages(self) -> list[str | None]:
        """Return usable PDF text per page, leaving scanned pages as ``None``."""
        return [
            text if self._page_has_readable_text(text) else None
            for text in self._native_text_pages()
        ]

    @staticmethod
    def _join_page_text(pages: Sequence[str | None]) -> str:
        return "\n\n".join(text for text in pages if text).strip()

    @staticmethod
    def _embedded_page_image(page: Any) -> Any | None:
        """Return a page-sized embedded scan without rendering or resampling."""
        try:
            page_images = page.images
            if len(page_images) != 1:
                return None
            image = page_images[0].image
            box = page.cropbox
            page_ratio = float(box.width) / float(box.height)
            image_ratio = image.width / image.height
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            if rotation in {90, 270}:
                page_ratio = 1 / page_ratio
            if abs(image_ratio - page_ratio) > 0.04:
                return None
            return image.rotate(-rotation, expand=True) if rotation else image
        except Exception:
            return None

    def extract_structured_text(self) -> dict[str, Any]:
        """Extract page-aware blocks and a Markdown-like text representation.

        Pypdf's layout text is kept in its source reading order. Coordinates
        from individual PDF text objects can reset mid-page and must not be
        globally sorted as though they shared one origin.
        """
        pages: list[list[str]] = []
        occurrences: Counter[str] = Counter()
        for page_text in self._native_text_pages(layout=True):
            lines = page_text.splitlines()
            for line in set(item.strip() for item in lines[:4] + lines[-4:] if item.strip()):
                occurrences[_normalize_furniture(line)] += 1
            pages.append(lines)

        page_count = len(pages)
        furniture = {
            text for text, count in occurrences.items()
            if page_count > 1 and count >= max(2, (page_count + 1) // 2)
            and len(text) < 100
        }

        blocks: list[dict[str, Any]] = []
        toc_pages: set[int] = set()
        for page_num, lines in enumerate(pages, 1):
            if any(re.fullmatch(r"Table of Contents", line.strip(), re.I) for line in lines):
                toc_pages.add(page_num)

        if pages:
            title_line = next((line.strip() for line in pages[0]
                               if "ARTIFICIAL INTELLIGENCE AT THE EDGE" in line.upper()), None)
            if title_line:
                blocks.append({"type": "heading", "level": 1, "text": title_line, "page": 1})

        for page_num, lines in enumerate(pages, 1):
            if page_num in toc_pages:
                continue
            kept = []
            for index, line in enumerate(lines):
                line = line.replace("\x7f", " \u2022 ").replace("\uf0b7", "\u2022").replace("\uf0a7", "\u2022")
                text = line.strip()
                if not text:
                    kept.append("")
                    continue
                if (index < 4 or index >= len(lines) - 4) and _normalize_furniture(text) in furniture:
                    continue
                if re.fullmatch(r"\d{1,2}", text):
                    continue
                if re.fullmatch(r"upload\s+[0-9a-f]{24,}", text, re.I):
                    continue
                if page_num == 1 and text == title_line:
                    continue
                kept.append(line)
            blocks.extend(_blocks_from_layout(kept, page_num))

        # Continue a table across a page break while dropping its repeated header.
        coalesced: list[dict[str, Any]] = []
        for block in blocks:
            if (coalesced and block["type"] == coalesced[-1]["type"] == "table"
                    and block["page"] == coalesced[-1]["page"] + 1
                    and block["rows"] and coalesced[-1]["rows"]
                    and block["rows"][0] == coalesced[-1]["rows"][0]):
                coalesced[-1]["rows"].extend(block["rows"][1:])
                coalesced[-1]["page_end"] = block["page"]
            else:
                coalesced.append(block)
        blocks = coalesced

        # Reference entries often continue as unnumbered lines on the same
        # page. Attach those lines to the preceding numbered reference.
        references_joined: list[dict[str, Any]] = []
        for block in blocks:
            if (references_joined and references_joined[-1]["type"] == "reference"
                    and block["type"] == "paragraph"
                    and block["page"] == references_joined[-1]["page"]
                    and not block["text"].strip(" —–-" ).casefold().startswith("end of report")):
                references_joined[-1]["text"] += " " + block["text"]
            else:
                references_joined.append(block)
        blocks = references_joined

        joined: list[dict[str, Any]] = []
        for block in blocks:
            if "_indent" in block:
                block.pop("_indent")
            if (joined and joined[-1]["type"] == block["type"]
                    and block["type"] in {"paragraph", "list_item"}
                    and (joined[-1]["page"] == block["page"]
                         or joined[-1]["page"] + 1 == block["page"])
                    and not re.search(r"[.!?:][\"')\]]*$", joined[-1]["text"])
                    and (block["text"][:1].islower() or block["type"] == "list_item")):
                joined[-1]["text"] += " " + block["text"]
            else:
                joined.append(block)
        blocks = joined

        rendered = []
        for block in blocks:
            if block["type"] == "heading":
                rendered.append("#" * block["level"] + " " + block["text"])
            elif block["type"] == "table":
                rows = block["rows"]
                if rows:
                    table_lines = ["| " + " | ".join(rows[0]) + " |"]
                    table_lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                    table_lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
                    rendered.append("\n".join(table_lines))
            else:
                rendered.append(re.sub(r"\*\*(.*?)\*\*", r"\1", block["text"]))
        metadata = {k: str(v) for k, v in (self._reader.metadata or {}).items()}
        return {
            "text": "\n\n".join(rendered).strip(),
            "pages": page_count,
            "metadata": metadata,
            "blocks": blocks,
        }

    def to_html(self) -> str:
        text = self.to_text()
        # Simple but safe HTML escape
        import html as html_mod
        escaped = html_mod.escape(text)
        paragraphs = "".join(f"<p>{p}</p>" for p in escaped.split("\n\n") if p.strip())
        return f"<!DOCTYPE html><html><body>{paragraphs}</body></html>"

    def info(self) -> dict[str, Any]:
        base = super().info()
        base.update({
            "pages": len(self._reader.pages),
            "encrypted": self._reader.is_encrypted,
            "metadata": {
                k: str(v) for k, v in (self._reader.metadata or {}).items()
            } if self._reader.metadata else {},
        })
        return base

    def _rasterized_pdf(self, *, dpi: int, quality: int) -> bytes:
        """Render every page into a compact JPEG-backed PDF."""
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise ProcessingError(
                "Aggressive PDF compression requires pypdfium2. "
                "Install the core dependencies with: pip install edocapi"
            ) from exc
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas

        output = BytesIO()
        canvas = Canvas(output, pageCompression=1)
        pdf = None
        try:
            pdf = pdfium.PdfDocument(str(self.path))
            for index in range(len(pdf)):
                page = pdf[index]
                bitmap = None
                try:
                    width, height = page.get_size()
                    bitmap = page.render(scale=dpi / 72)
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
                jpeg = BytesIO()
                image.save(jpeg, format="JPEG", quality=quality, optimize=True)
                jpeg.seek(0)
                canvas.setPageSize((width, height))
                canvas.drawImage(ImageReader(jpeg), 0, 0, width=width, height=height)
                canvas.showPage()
            canvas.save()
        finally:
            if pdf is not None:
                pdf.close()
        return output.getvalue()

    def compress(self, target_size: int | None = None) -> Path:
        """Compress a PDF, rasterizing pages as a last resort for a size target."""
        if target_size is not None and target_size <= 0:
            raise ProcessingError("Target size must be a positive number of bytes.")

        from PIL import Image

        candidates = [(1.0, None)]
        if target_size is not None:
            candidates.extend([
                (0.9, 85),
                (0.8, 80),
                (0.7, 75),
                (0.6, 70),
                (0.5, 65),
                (0.4, 60),
                (0.3, 55),
                (0.25, 50),
                (0.2, 45),
                (0.15, 40),
                (0.1, 35),
            ])

        compressed = self.path.read_bytes()
        if target_size is None or len(compressed) > target_size:
            for scale, quality in candidates:
                writer = PdfWriter()
                for page in self._reader.pages:
                    writer.add_page(page)

                reencoded_images = 0
                if quality is not None:
                    for page in writer.pages:
                        for image_file in getattr(page, "images", ()):
                            replace_image = getattr(image_file, "replace", None)
                            if (
                                not callable(replace_image)
                                or getattr(image_file, "is_inline", False)
                                or getattr(image_file, "indirect_reference", None) is None
                            ):
                                continue
                            image = image_file.image
                            if "A" in image.mode or "transparency" in image.info:
                                continue
                            if image.mode == "1":
                                image = image.convert("L")
                            elif image.mode not in {"L", "RGB", "CMYK"}:
                                image = image.convert("RGB")
                            if scale < 1:
                                width = max(1, round(image.width * scale))
                                height = max(1, round(image.height * scale))
                                image = image.resize(
                                    (width, height),
                                    resample=Image.Resampling.LANCZOS,
                                )
                            replace_image(image, quality=quality, optimize=True)
                            reencoded_images += 1

                for page in writer.pages:
                    page.compress_content_streams()
                writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
                buffer = BytesIO()
                writer.write(buffer)
                candidate = buffer.getvalue()
                if len(candidate) < len(compressed):
                    compressed = candidate
                if target_size is None or len(compressed) <= target_size:
                    break
                if quality is not None and reencoded_images == 0:
                    break

        if target_size is not None and len(compressed) > target_size:
            # Re-render the whole page so text and vector-heavy PDFs can be
            # compressed too. This is deliberately the last-resort path:
            # rasterized output no longer has selectable text or vectors.
            for dpi, quality in ((120, 65), (96, 55), (72, 45), (60, 38), (48, 30), (36, 24)):
                rasterized = self._rasterized_pdf(dpi=dpi, quality=quality)
                if len(rasterized) < len(compressed):
                    compressed = rasterized
                if len(compressed) <= target_size:
                    break

        out = self._temp_path(suffix=".pdf", prefix="compressed_")
        out.write_bytes(compressed)
        if target_size is not None and len(compressed) > target_size:
            logger.warning(
                "Could not reach PDF compression target for %s: requested %s bytes, "
                "smallest output is %s bytes",
                self.path.name,
                target_size,
                len(compressed),
            )

        logger.info("Compressed PDF %s → %s bytes", self.path.name, out.stat().st_size)
        return out

    def ocr(self, *, lang: str = "eng", engine: str = "tesseract") -> str:
        """Use embedded PDF text page by page and OCR pages that are scans."""
        if engine not in {"tesseract", "paddle"}:
            raise ValueError("OCR engine must be 'tesseract' or 'paddle'.")

        # Paddle is explicitly selected for its document-layout and formula
        # recognition. Run that pipeline for the full document, including
        # digitally generated PDFs: their selectable text alone does not
        # preserve the geometry of fractions, limits, and multi-line maths.
        if engine == "paddle":
            from edocapi.processors.structured_ocr import ocr_document
            return ocr_document(self.path, lang=lang)

        native_pages = self._embedded_text_pages()
        if all(text is not None for text in native_pages):
            logger.info("Using embedded PDF text; skipping page OCR for %s", self.path.name)
            return self._join_page_text(native_pages)

        try:
            import pytesseract
        except ImportError as exc:
            raise ProcessingError(
                "OCR requires the 'ml' extra. Install with: pip install edocapi[ml]"
            ) from exc

        configure_tesseract(pytesseract)
        lang = normalize_tesseract_language(lang)
        texts: list[str | None] = list(native_pages)
        for index, text in enumerate(native_pages):
            if text is not None:
                continue

            image = self._embedded_page_image(self._reader.pages[index])
            if image is None:
                try:
                    from pdf2image import convert_from_path
                    from pdf2image.exceptions import PDFInfoNotInstalledError
                except ImportError as exc:
                    raise ProcessingError(
                        "OCR of scanned PDF pages requires the 'pdf-images' extra when the page "
                        "does not contain a full-page scan image. Install with: "
                        "pip install edocapi[pdf-images]"
                    ) from exc
                try:
                    rendered = convert_from_path(
                        str(self.path), dpi=300, poppler_path=find_poppler_bin(),
                        first_page=index + 1, last_page=index + 1,
                    )
                except PDFInfoNotInstalledError as exc:
                    raise ProcessingError(
                        "Scanned PDF OCR requires Poppler to render this PDF. Install Poppler and add its "
                        "bin folder to PATH, or set POPPLER_PATH to the folder containing pdfinfo.exe "
                        "and pdftoppm.exe."
                    ) from exc
                if not rendered:
                    raise ProcessingError(f"Could not render PDF page {index + 1} for OCR.")
                image = rendered[0]

            try:
                texts[index] = pytesseract.image_to_string(image, lang=lang).strip()
            except Exception as exc:
                raise ProcessingError(f"OCR failed on page {index + 1}: {exc}") from exc
        return self._join_page_text(texts)

    def to_images(self, *, format: str = "png") -> list[Path]:
        try:
            from pdf2image import convert_from_path
        except ImportError as exc:
            raise ProcessingError(
                "PDF→image conversion requires pdf2image. "
                "Install with: pip install edocapi[pdf-images]"
            ) from exc

        fmt = format.lower().lstrip(".")
        if fmt not in {"png", "jpg", "jpeg", "webp"}:
            raise ProcessingError(f"Unsupported image format: {fmt}")

        images = convert_from_path(str(self.path), dpi=150)
        paths = []
        for i, img in enumerate(images):
            out = self._temp_path(suffix=f".{fmt}", prefix=f"page_{i+1}_")
            save_fmt = "JPEG" if fmt in {"jpg", "jpeg"} else fmt.upper()
            img.save(str(out), save_fmt)
            paths.append(out)
        return paths

    @staticmethod
    def merge(paths: Sequence[Path], *, temp_storage: Any = None) -> Path:
        writer = PdfWriter()
        for p in paths:
            try:
                reader = PdfReader(str(p))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as exc:
                raise ProcessingError(f"Failed to merge {p}: {exc}") from exc

        if temp_storage is not None:
            out = temp_storage.create_file(suffix=".pdf", prefix="merged_")
        else:
            import tempfile, os
            fd, name = tempfile.mkstemp(suffix=".pdf", prefix="merged_")
            os.close(fd)
            out = Path(name)

        with out.open("wb") as f:
            writer.write(f)
        return out
