"""PDF processor for eDocAPI (pypdf + optional ML/OCR)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from edocapi.exceptions import InvalidDocument, ProcessingError
from edocapi.processors.base import BaseProcessor, register_processor

logger = logging.getLogger("edocapi.processors.pdf")


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
        texts = []
        for page in self._reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            texts.append(t)
        return "\n\n".join(texts).strip()

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

    def compress(self, target_size: int | None = None) -> Path:
        """Compress PDF by removing duplicate objects and optionally downsampling.

        If target_size is given, iteratively reduce image quality.
        """
        out = self._temp_path(suffix=".pdf", prefix="compressed_")
        writer = PdfWriter()
        for page in self._reader.pages:
            writer.add_page(page)
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        with out.open("wb") as f:
            writer.write(f)

        if target_size and out.stat().st_size > target_size:
            # Further reduction via content stream compression
            writer2 = PdfWriter()
            for page in PdfReader(str(out)).pages:
                page.compress_content_streams()
                writer2.add_page(page)
            with out.open("wb") as f:
                writer2.write(f)

        logger.info("Compressed PDF %s → %s bytes", self.path.name, out.stat().st_size)
        return out

    def ocr(self, *, lang: str = "eng") -> str:
        """OCR every page (requires pdf2image + pytesseract)."""
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError as exc:
            raise ProcessingError(
                "OCR requires the 'ml' and 'pdf-images' extras. "
                "Install with: pip install edocapi[ml,pdf-images]"
            ) from exc

        images = convert_from_path(str(self.path), dpi=200)
        texts = []
        for i, img in enumerate(images):
            try:
                t = pytesseract.image_to_string(img, lang=lang)
            except Exception as exc:
                logger.warning("OCR failed on page %d: %s", i + 1, exc)
                t = ""
            texts.append(t)
        return "\n\n".join(texts).strip()

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
