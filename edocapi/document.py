"""Document abstraction for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from edocapi.exceptions import ConversionError, InvalidDocument, ProcessingError
from edocapi.processors.base import get_processor_class, list_supported_types
from edocapi.storage.temporary import TemporaryStorage, safe_filename
from edocapi.validation.files import validate_file

logger = logging.getLogger("edocapi.document")


class Document:
    """High-level document abstraction.

    Developers interact primarily with this class::

        Document(file).to_pdf()
        Document(file).extract_text()
        Document.merge([f1, f2])
        Document(file).ocr()          # ML-powered OCR (optional)
    """

    def __init__(
        self,
        source: Path | str | bytes | None = None,
        *,
        filename: str | None = None,
        doc_type: str | None = None,
        temp_storage: TemporaryStorage | None = None,
        max_size: int = 50 * 1024 * 1024,
        strict_magic: bool = True,
    ) -> None:
        self._temp = temp_storage or TemporaryStorage()
        self._max_size = max_size
        self._path: Path | None = None
        self._type: str | None = doc_type
        self._name: str | None = filename
        self._compression_mode: str | None = None
        self._original_name: str | None = None

        if source is None:
            return  # empty document (used by classmethods)

        if isinstance(source, (str, Path)):
            path = Path(source)
            self._path = path
            self._name = filename or path.name
            self._type = validate_file(path, max_size=max_size, strict_magic=strict_magic)
        elif isinstance(source, bytes):
            if not filename:
                raise InvalidDocument("filename is required when creating Document from bytes")
            safe = safe_filename(filename)
            path = self._temp.create_file(
                suffix=Path(safe).suffix,
                prefix="doc_",
                content=source,
            )
            self._path = path
            self._name = safe
            self._type = validate_file(path, max_size=max_size, strict_magic=strict_magic)
        else:
            raise TypeError(
                f"Unsupported source type for Document: {type(source)}. "
                "Expected Path, str, or bytes."
            )

        logger.debug("Document created: %s (type=%s)", self._name, self._type)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        if self._path is None:
            raise InvalidDocument("Document has no underlying file path.")
        return self._path

    @property
    def name(self) -> str:
        return self._name or (self._path.name if self._path else "unnamed")

    @property
    def size(self) -> int:
        return self.path.stat().st_size

    @property
    def type(self) -> str:
        return self._type or "unknown"

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    @property
    def mime_type(self) -> str:
        import mimetypes
        mime, _ = mimetypes.guess_type(self.name)
        return mime or "application/octet-stream"

    # ------------------------------------------------------------------
    # Class constructors
    # ------------------------------------------------------------------

    @classmethod
    def html(cls, content: str, *, filename: str = "document.html") -> "Document":
        return cls(content.encode("utf-8"), filename=filename, doc_type="html")

    @classmethod
    def markdown(cls, content: str, *, filename: str = "document.md") -> "Document":
        return cls(content.encode("utf-8"), filename=filename, doc_type="markdown")

    @classmethod
    def text(cls, content: str, *, filename: str = "document.txt") -> "Document":
        return cls(content.encode("utf-8"), filename=filename, doc_type="txt")

    @classmethod
    def supported_types(cls) -> list[str]:
        return list_supported_types()

    # ------------------------------------------------------------------
    # Processor access
    # ------------------------------------------------------------------

    def _processor(self):
        cls = get_processor_class(self.type)
        return cls(self.path, temp_storage=self._temp)

    # ------------------------------------------------------------------
    # Conversion methods
    # ------------------------------------------------------------------

    def to_pdf(self) -> "Document":
        """Convert this document to PDF and return a new Document."""
        logger.info("Converting %s -> PDF", self.name)
        try:
            out_path = self._processor().to_pdf()
            return Document(out_path, filename=out_path.name, doc_type="pdf", temp_storage=self._temp)
        except Exception as exc:
            raise ConversionError(f"Failed to convert {self.name} to PDF: {exc}") from exc

    def to_text(self) -> str:
        """Extract plain text."""
        return self._processor().to_text()

    def extract_text(self) -> str:
        """Alias for to_text()."""
        return self.to_text()

    def to_html(self) -> str:
        return self._processor().to_html()

    def to_images(self, *, format: str = "png") -> list["Document"]:
        paths = self._processor().to_images(format=format)
        return [
            Document(p, filename=p.name, doc_type=format, temp_storage=self._temp)
            for p in paths
        ]

    def info(self) -> dict[str, Any]:
        return self._processor().info()

    def compress(self, target_size: int | None = None) -> "Document":
        """Compress PDF or image. Optionally aim for a target size in bytes."""
        proc = self._processor()
        if not hasattr(proc, "compress"):
            raise ProcessingError(f"Compression not supported for type '{self.type}'.")
        out = proc.compress(target_size=target_size)
        doc = Document(out, filename=out.name, doc_type=self.type, temp_storage=self._temp)
        doc._compression_mode = "image" if self.type in {"jpeg", "jpg", "png", "webp"} else "pdf"
        doc._original_name = self.name
        return doc

    def ocr(self, *, lang: str = "eng") -> str:
        """ML-powered OCR – extract text from images or scanned PDFs.

        Requires the optional ``ml`` extra::

            pip install edocapi[ml]
        """
        proc = self._processor()
        if hasattr(proc, "ocr"):
            return proc.ocr(lang=lang)
        # Fallback: try image OCR via Pillow + pytesseract for image types
        if self.type in {"jpeg", "jpg", "png", "webp"}:
            from edocapi.processors.image import ImageProcessor
            return ImageProcessor(self.path, temp_storage=self._temp).ocr(lang=lang)
        raise ProcessingError(
            f"OCR is not available for type '{self.type}'. "
            "Install the ML extra: pip install edocapi[ml]"
        )

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def merge(cls, files: Sequence[Path | str | "Document"], *, temp_storage: TemporaryStorage | None = None) -> "Document":
        """Merge multiple PDF documents into one."""
        from edocapi.processors.pdf import PDFProcessor

        temp = temp_storage or TemporaryStorage()
        paths: list[Path] = []
        for f in files:
            if isinstance(f, Document):
                paths.append(f.path)
            else:
                paths.append(Path(f))

        if not paths:
            raise ProcessingError("No files provided for merge.")

        out = PDFProcessor.merge(paths, temp_storage=temp)
        return cls(out, filename=out.name, doc_type="pdf", temp_storage=temp)
