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
    """

    def __init__(
        self,
        source: Path | str | bytes | None = None,
        *,
        filename: str | None = None,
        doc_type: str | None = None,
        temp_storage: TemporaryStorage | None = None,
        max_size: int = 50 * 1024 * 1024,
    ) -> None:
        self._temp = temp_storage or TemporaryStorage()
        self._max_size = max_size
        self._path: Path | None = None
        self._type: str | None = doc_type
        self._name: str | None = filename

        if source is None:
            return  # empty document (used by classmethods)

        if isinstance(source, (str, Path)):
            path = Path(source)
            self._path = path
            self._name = filename or path.name
            self._type = validate_file(path, max_size=max_size)
        elif isinstance(source, bytes):
            if not filename:
                raise InvalidDocument("filename is required when creating Document from bytes")
            safe = safe_filename(filename)
            path = self._temp.create_file(
                suffix=Path(safe).suffix,
                prefix="doc_",
                content=source,
            )
            # Rename to keep original name
            target = path.with_name(safe)
            if target != path:
                path.rename(target)
                path = target
            self._path = path
            self._name = safe
            self._type = validate_file(path, max_size=max_size)
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
    # Class constructors for in-memory content
    # ------------------------------------------------------------------

    @classmethod
    def html(cls, content: str, *, filename: str = "document.html") -> "Document":
        """Create a Document from an HTML string."""
        data = content.encode("utf-8")
        return cls(data, filename=filename, doc_type="html")

    @classmethod
    def markdown(cls, content: str, *, filename: str = "document.md") -> "Document":
        """Create a Document from a Markdown string."""
        data = content.encode("utf-8")
        return cls(data, filename=filename, doc_type="markdown")

    @classmethod
    def text(cls, content: str, *, filename: str = "document.txt") -> "Document":
        """Create a Document from plain text."""
        data = content.encode("utf-8")
        return cls(data, filename=filename, doc_type="txt")

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
            return Document(out_path, temp_storage=self._temp)
        except Exception as exc:
            message = str(exc)
            if "libgobject" in message.lower() or "cannot load library" in message.lower():
                message = (
                    "WeasyPrint's native GTK libraries are missing. On Windows, "
                    "install the GTK3 runtime, add its bin directory to PATH, "
                    "then restart the terminal and server."
                )
            raise ConversionError(
                message, source=self.type, target="pdf"
            ) from exc

    def to_text(self) -> str:
        """Extract plain text content."""
        logger.info("Extracting text from %s", self.name)
        try:
            return self._processor().to_text()
        except NotImplementedError:
            raise ConversionError(
                f"Text extraction not supported for type '{self.type}'.",
                source=self.type,
                target="txt",
            )
        except Exception as exc:
            raise ConversionError(str(exc), source=self.type, target="txt") from exc

    def extract_text(self) -> str:
        """Alias for to_text()."""
        return self.to_text()

    def to_html(self) -> str:
        """Convert to HTML string."""
        logger.info("Converting %s -> HTML", self.name)
        try:
            return self._processor().to_html()
        except NotImplementedError:
            raise ConversionError(
                f"HTML conversion not supported for type '{self.type}'.",
                source=self.type,
                target="html",
            )
        except Exception as exc:
            raise ConversionError(str(exc), source=self.type, target="html") from exc

    def to_images(self, *, format: str = "png") -> list["Document"]:
        """Convert pages to images. Returns a list of Document objects."""
        logger.info("Converting %s -> images (%s)", self.name, format)
        try:
            paths = self._processor().to_images(format=format)
            return [Document(p, temp_storage=self._temp) for p in paths]
        except NotImplementedError:
            raise ConversionError(
                f"Image conversion not supported for type '{self.type}'.",
                source=self.type,
                target="images",
            )
        except Exception as exc:
            raise ConversionError(str(exc), source=self.type, target="images") from exc

    # ------------------------------------------------------------------
    # PDF operations (delegated when type is PDF)
    # ------------------------------------------------------------------

    def info(self) -> dict[str, Any]:
        """Return document metadata / information."""
        try:
            return self._processor().info()
        except Exception:
            # Fallback basic info
            return {
                "filename": self.name,
                "type": self.type,
                "size": self.size,
                "extension": self.extension,
                "mime_type": self.mime_type,
            }

    def compress(self, level: str = "medium", target_size: int | None = None) -> "Document":
        """Compress a PDF or supported raster image; optionally set a byte target."""
        if self.type in {"jpeg", "jpg", "png", "webp"}:
            from edocapi.processors.image import ImageProcessor

            proc = ImageProcessor(self.path, temp_storage=self._temp)
            out = proc.compress(level=level, target_size=target_size)
            result = Document(out, temp_storage=self._temp)
            result._original_name = self.name
            result._compression_mode = "image"
            return result
        if self.type != "pdf":
            raise ProcessingError(
                "compress() supports PDF, JPG, JPEG, PNG, and WebP files only."
            )
        from edocapi.processors.pdf import PDFProcessor

        proc = PDFProcessor(self.path, temp_storage=self._temp)
        out = proc.compress(level=level, target_size=target_size)
        result = Document(out, temp_storage=self._temp)
        result._compression_mode = getattr(proc, "_last_compression_mode", "optimized")
        return result

    def split(self) -> list["Document"]:
        """Split a PDF into individual pages."""
        if self.type != "pdf":
            raise ProcessingError("split() is only available for PDF documents.")
        from edocapi.processors.pdf import PDFProcessor

        proc = PDFProcessor(self.path, temp_storage=self._temp)
        paths = proc.split()
        return [Document(p, temp_storage=self._temp) for p in paths]

    def extract_pages(self, start: int, end: int | None = None) -> "Document":
        """Extract a page range (1-based inclusive)."""
        if self.type != "pdf":
            raise ProcessingError("extract_pages() is only available for PDF documents.")
        from edocapi.processors.pdf import PDFProcessor

        proc = PDFProcessor(self.path, temp_storage=self._temp)
        out = proc.extract_pages(start, end)
        return Document(out, temp_storage=self._temp)

    def rotate(self, degrees: int = 90, pages: Sequence[int] | None = None) -> "Document":
        """Rotate pages (1-based). Default rotates all pages by 90 degrees."""
        if self.type != "pdf":
            raise ProcessingError("rotate() is only available for PDF documents.")
        from edocapi.processors.pdf import PDFProcessor

        proc = PDFProcessor(self.path, temp_storage=self._temp)
        out = proc.rotate(degrees, pages=pages)
        return Document(out, temp_storage=self._temp)

    # ------------------------------------------------------------------
    # Class-level operations
    # ------------------------------------------------------------------

    @classmethod
    def merge(cls, files: Sequence[Path | str | "Document"]) -> "Document":
        """Merge multiple PDF documents into one."""
        from edocapi.processors.pdf import PDFProcessor

        paths: list[Path] = []
        for f in files:
            if isinstance(f, Document):
                paths.append(f.path)
            else:
                paths.append(Path(f))

        if not paths:
            raise ProcessingError("No files provided for merge.")

        temp = TemporaryStorage()
        out = PDFProcessor.merge(paths, temp_storage=temp)
        return cls(out, temp_storage=temp)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<Document name={self.name!r} type={self.type!r} size={self.size}>"

    @staticmethod
    def supported_types() -> list[str]:
        return list_supported_types()
