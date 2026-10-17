"""Document abstraction for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from edocapi.exceptions import ConversionError, InvalidDocument, ProcessingError, UnsupportedFileType
from edocapi.config import MAX_FILE_SIZE_BYTES
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
        max_size: int = MAX_FILE_SIZE_BYTES,
        strict_magic: bool = True,
        allowed_extensions: set[str] | None = None,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be greater than zero.")
        if max_size > MAX_FILE_SIZE_BYTES:
            raise ValueError("max_size cannot exceed the framework limit of 50MB.")

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
            if allowed_extensions is not None:
                self._check_allowed_extension(self._name, allowed_extensions)
            self._type = validate_file(
                path, max_size=max_size, strict_magic=strict_magic,
                allowed_extensions=allowed_extensions,
            )
        elif isinstance(source, bytes):
            if not filename:
                raise InvalidDocument("filename is required when creating Document from bytes")
            if not source:
                raise InvalidDocument("Document content cannot be empty.")
            safe = safe_filename(filename)
            if allowed_extensions is not None:
                self._check_allowed_extension(safe, allowed_extensions)
            path = self._temp.create_file(
                suffix=Path(safe).suffix,
                prefix="doc_",
                content=source,
            )
            self._path = path
            self._name = safe
            try:
                self._type = validate_file(
                    path, max_size=max_size, strict_magic=strict_magic,
                    allowed_extensions=allowed_extensions,
                )
            except Exception:
                self._temp.discard(path)
                raise
        else:
            raise TypeError(
                f"Unsupported source type for Document: {type(source)}. "
                "Expected Path, str, or bytes."
            )

        logger.debug("Document created: %s (type=%s)", self._name, self._type)

    @staticmethod
    def _check_allowed_extension(filename: str, allowed_extensions: set[str]) -> None:
        extension = Path(filename).suffix.lower()
        normalized = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_extensions}
        if extension not in normalized:
            raise InvalidDocument(f"File extension '{extension or '(none)'}' is not allowed.")

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
        if self._path is None or self._type is None:
            raise InvalidDocument("Document is empty or has no validated source file.")
        cls = get_processor_class(self.type)
        return cls(self.path, temp_storage=self._temp)

    # ------------------------------------------------------------------
    # Conversion methods
    # ------------------------------------------------------------------

    def to_pdf(self) -> "Document":
        """Convert this document to PDF and return a new Document."""
        logger.info("Converting %s -> PDF", self.name)
        out_path: Path | None = None
        try:
            out_path = self._processor().to_pdf()
            if not out_path.is_file() or out_path.stat().st_size == 0:
                raise ConversionError("Converter produced an empty or missing PDF.")
            return Document(out_path, filename=out_path.name, doc_type="pdf", temp_storage=self._temp)
        except (InvalidDocument, UnsupportedFileType):
            if out_path is not None:
                self._temp.discard(out_path)
            raise
        except ConversionError:
            if out_path is not None:
                self._temp.discard(out_path)
            raise
        except Exception as exc:
            if out_path is not None:
                self._temp.discard(out_path)
            logger.exception("PDF conversion failed for %s", self.name)
            raise ConversionError(f"Failed to convert '{self.name}' to PDF.") from exc

    def to_text(self) -> str:
        """Extract plain text."""
        return self._processor().to_text()

    def extract_text(self) -> str:
        """Alias for to_text()."""
        return self.to_text()

    def extract_structured_text(self) -> dict[str, Any]:
        """Return PDF text with page-level blocks and PDF metadata."""
        processor = self._processor()
        if not hasattr(processor, "extract_structured_text"):
            raise ProcessingError(
                f"Structured text extraction is not supported for type '{self.type}'."
            )
        return processor.extract_structured_text()

    def to_html(self) -> str:
        return self._processor().to_html()

    def to_images(self, *, format: str = "png") -> list["Document"]:
        paths: list[Path] = []
        try:
            paths = self._processor().to_images(format=format)
            if not paths or any(not p.is_file() or p.stat().st_size == 0 for p in paths):
                raise ProcessingError("Image converter produced no output or an empty image.")
            return [
                Document(p, filename=p.name, doc_type=format, temp_storage=self._temp)
                for p in paths
            ]
        except Exception:
            for path in paths:
                self._temp.discard(path)
            raise

    def info(self) -> dict[str, Any]:
        return self._processor().info()

    def compress(self, target_size: int | None = None) -> "Document":
        """Compress a PDF or image, optionally requiring a target size in bytes."""
        proc = self._processor()
        if not hasattr(proc, "compress"):
            raise ProcessingError(f"Compression not supported for type '{self.type}'.")
        out = proc.compress(target_size=target_size)
        output_type = out.suffix.lower().lstrip(".")
        doc = Document(out, filename=out.name, doc_type=output_type, temp_storage=self._temp)
        doc._compression_mode = "image" if self.type in {"jpeg", "jpg", "png", "webp"} else "pdf"
        doc._original_name = self.name
        if doc._compression_mode == "image" and target_size is not None:
            doc._compression_target_met = out.stat().st_size <= target_size
            doc._compression_target_size = target_size
        elif self.type == "pdf" and target_size is not None:
            doc._compression_target_met = out.stat().st_size <= target_size
            doc._compression_target_size = target_size
        return doc

    def ocr(self, *, lang: str = "eng", engine: str = "tesseract") -> str:
        """Extract PDF text directly and OCR only pages that contain scans.

        ``engine="tesseract"`` uses the optional ``ml`` extra when a page needs OCR. Use
        ``engine="paddle"`` for document layout and formula recognition; that
        backend uses the optional ``structured-ocr`` extra and supported
        PaddlePaddle Python versions::

            pip install edocapi[ml]
            pip install edocapi[structured-ocr]
        """
        if engine not in {"tesseract", "paddle"}:
            raise ProcessingError("OCR engine must be 'tesseract' or 'paddle'.")

        # Tesseract uses embedded PDF text when available. Paddle is an
        # explicit request for full document and formula reconstruction.
        if self.type == "pdf":
            return self._processor().ocr(lang=lang, engine=engine)

        if engine == "paddle":
            from edocapi.processors.structured_ocr import ocr_document
            if self.type not in {"jpeg", "jpg", "png", "webp"}:
                raise ProcessingError(f"Structured OCR is not available for type '{self.type}'.")
            return ocr_document(self.path, lang=lang)

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

        owns_temp = temp_storage is None
        temp = temp_storage or TemporaryStorage()
        paths: list[Path] = []
        try:
            for f in files:
                if isinstance(f, Document):
                    path = f.path
                else:
                    path = Path(f)
                validate_file(path, max_size=MAX_FILE_SIZE_BYTES, strict_magic=True)
                if path.suffix.lower() != ".pdf":
                    raise InvalidDocument(f"Merge only accepts PDF files: {path.name}")
                from edocapi.processors.pdf import PDFProcessor
                PDFProcessor(path, temp_storage=temp)
                paths.append(path)

            if not paths:
                raise ProcessingError("No files provided for merge.")

            out = PDFProcessor.merge(paths, temp_storage=temp)
            return cls(out, filename=out.name, doc_type="pdf", temp_storage=temp)
        except Exception:
            if owns_temp:
                temp.cleanup()
            raise
