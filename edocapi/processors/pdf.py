"""PDF processor for eDocAPI (uses pypdf)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from edocapi.exceptions import InvalidDocument, ProcessingError
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi.processors.pdf")


@register_processor("pdf")
class PDFProcessor(BaseProcessor):
    """Processor for PDF documents."""

    supported_input_types = {"pdf"}
    supported_output_types = {"pdf", "txt", "html", "png", "jpg", "webp"}

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        super().__init__(path, temp_storage=temp_storage)
        try:
            self._reader = PdfReader(str(path))
        except PdfReadError as exc:
            raise InvalidDocument(f"Invalid or corrupted PDF: {exc}") from exc

    # ------------------------------------------------------------------
    # Basic conversions
    # ------------------------------------------------------------------

    def to_pdf(self) -> Path:
        """Return a copy of the PDF (identity conversion)."""
        out = self._temp_path(suffix=".pdf", prefix="copy_")
        writer = PdfWriter()
        for page in self._reader.pages:
            writer.add_page(page)
        with out.open("wb") as f:
            writer.write(f)
        return out

    def to_text(self) -> str:
        """Extract text from all pages."""
        parts: list[str] = []
        for i, page in enumerate(self._reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"--- Page {i} ---\n{text.strip()}")
        return "\n\n".join(parts)

    def to_html(self) -> str:
        """Simple HTML representation of extracted text."""
        text = self.to_text()
        # Very basic wrapping  not a full visual conversion
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>\n")
        )
        return f"<html><body><pre>{escaped}</pre></body></html>"

    def to_images(self, *, format: str = "png") -> list[Path]:
        """Convert PDF pages to images.

        Requires the optional `pdf2image` package (and poppler).
        If unavailable, raises a clear ProcessingError.
        """
        try:
            from pdf2image import convert_from_path
        except ImportError as exc:
            raise ProcessingError(
                "PDF -> images requires the optional dependency 'pdf2image' "
                "and the system package 'poppler'. "
                "Install with: pip install pdf2image"
            ) from exc

        fmt = format.lower().lstrip(".")
        if fmt not in {"png", "jpg", "jpeg", "webp"}:
            raise ProcessingError(f"Unsupported image format: {format}")

        images = convert_from_path(str(self.path))
        paths: list[Path] = []
        for i, img in enumerate(images, start=1):
            suffix = f".{fmt if fmt != 'jpeg' else 'jpg'}"
            out = self._temp_path(suffix=suffix, prefix=f"page_{i}_")
            img.save(str(out), fmt.upper() if fmt != "jpg" else "JPEG")
            paths.append(out)
        return paths

    def info(self) -> dict[str, Any]:
        meta = self._reader.metadata or {}
        return {
            "filename": self.path.name,
            "type": "pdf",
            "pages": len(self._reader.pages),
            "size": self.path.stat().st_size,
            "extension": ".pdf",
            "title": getattr(meta, "title", None) or meta.get("/Title"),
            "author": getattr(meta, "author", None) or meta.get("/Author"),
            "subject": getattr(meta, "subject", None) or meta.get("/Subject"),
            "creator": getattr(meta, "creator", None) or meta.get("/Creator"),
            "producer": getattr(meta, "producer", None) or meta.get("/Producer"),
            "creation_date": str(getattr(meta, "creation_date", None) or meta.get("/CreationDate") or ""),
            "modification_date": str(getattr(meta, "modification_date", None) or meta.get("/ModDate") or ""),
        }

    # ------------------------------------------------------------------
    # PDF operations
    # ------------------------------------------------------------------

    def compress(self, level: str = "medium") -> Path:
        """Compress the PDF.

        Levels:
            low     minimal compression (mostly remove unused objects)
            medium  default, moderate image quality reduction if possible
            high    aggressive (may reduce quality)

        Note: pypdf's compression is limited; this is a best-effort implementation.
        """
        level = level.lower()
        if level not in {"low", "medium", "high"}:
            raise ProcessingError(f"Unknown compression level: {level}")

        writer = PdfWriter()
        for page in self._reader.pages:
            writer.add_page(page)
            # Work on the writer-owned copy; add_page may clone the reader page.
            writer.pages[-1].compress_content_streams()

        # Remove unused objects / metadata for higher levels
        if level in {"medium", "high"}:
            try:
                writer.compress_identical_objects(
                    remove_duplicates=True, remove_unreferenced=True
                )
            except TypeError:
                # older pypdf API
                writer.compress_identical_objects(
                    remove_identicals=True, remove_orphans=True
                )

        out = self._temp_path(suffix=".pdf", prefix="compressed_")
        with out.open("wb") as f:
            writer.write(f)
        return out

    def split(self) -> list[Path]:
        """Split into one PDF per page."""
        paths: list[Path] = []
        for i, page in enumerate(self._reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            out = self._temp_path(suffix=".pdf", prefix=f"page_{i}_")
            with out.open("wb") as f:
                writer.write(f)
            paths.append(out)
        return paths

    def extract_pages(self, start: int, end: int | None = None) -> Path:
        """Extract pages start..end (1-based inclusive)."""
        total = len(self._reader.pages)
        if start < 1 or start > total:
            raise ProcessingError(f"Start page {start} out of range (1-{total}).")
        if end is None:
            end = total
        if end < start or end > total:
            raise ProcessingError(f"End page {end} out of range ({start}-{total}).")

        writer = PdfWriter()
        for i in range(start - 1, end):  # convert to 0-based
            writer.add_page(self._reader.pages[i])

        out = self._temp_path(
            suffix=".pdf",
            prefix=f"pages_{start}-{end}_",
        )
        with out.open("wb") as f:
            writer.write(f)
        return out

    def rotate(self, degrees: int = 90, pages: Sequence[int] | None = None) -> Path:
        """Rotate pages by degrees (90, 180, 270). pages is 1-based."""
        if degrees % 90 != 0:
            raise ProcessingError("Rotation must be a multiple of 90 degrees.")

        writer = PdfWriter()
        total = len(self._reader.pages)
        page_set = set(pages) if pages else None

        for i, page in enumerate(self._reader.pages, start=1):
            if page_set is None or i in page_set:
                page.rotate(degrees)
            writer.add_page(page)

        out = self._temp_path(suffix=".pdf", prefix="rotated_")
        with out.open("wb") as f:
            writer.write(f)
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _temp_path(self, suffix: str = "", prefix: str = "pdf_") -> Path:
        storage = self.temp_storage or TemporaryStorage()
        return storage.create_file(suffix=suffix, prefix=prefix)

    @staticmethod
    def merge(paths: Sequence[Path], *, temp_storage: TemporaryStorage | None = None) -> Path:
        """Merge multiple PDFs into one."""
        writer = PdfWriter()
        for p in paths:
            try:
                reader = PdfReader(str(p))
                for page in reader.pages:
                    writer.add_page(page)
            except PdfReadError as exc:
                raise InvalidDocument(f"Cannot read PDF for merge: {p.name}: {exc}") from exc

        storage = temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="merged_")
        with out.open("wb") as f:
            writer.write(f)
        return out
