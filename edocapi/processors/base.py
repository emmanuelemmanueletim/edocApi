"""Base processor and registry for eDocAPI document processors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Type

logger = logging.getLogger("edocapi.processors")


class BaseProcessor(ABC):
    """Abstract base class for format-specific document processors."""

    # Formats this processor can handle as input (e.g. {"pdf"}, {"docx", "doc"})
    supported_input_types: set[str] = set()

    # Formats this processor can produce as output
    supported_output_types: set[str] = set()

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        self.path = Path(path)
        self.temp_storage = temp_storage

    @abstractmethod
    def to_pdf(self) -> Path:
        """Convert the document to PDF. Returns path to the PDF file."""
        ...

    def to_text(self) -> str:
        """Extract plain text from the document."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support text extraction."
        )

    def to_html(self) -> str:
        """Convert the document to HTML string."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support HTML conversion."
        )

    def to_images(self, *, format: str = "png") -> list[Path]:
        """Convert document pages to images. Returns list of image paths."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support image conversion."
        )

    def info(self) -> dict[str, Any]:
        """Return basic information about the document."""
        stat = self.path.stat()
        return {
            "filename": self.path.name,
            "type": next(iter(self.supported_input_types), "unknown"),
            "size": stat.st_size,
            "extension": self.path.suffix.lower(),
        }

    def extract_text(self) -> str:
        """Alias for to_text() for clearer naming."""
        return self.to_text()


# ---------------------------------------------------------------------------
# Processor registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Type[BaseProcessor]] = {}


def register_processor(
    *types: str,
) -> callable:
    """Decorator to register a processor for one or more input types."""

    def decorator(cls: Type[BaseProcessor]) -> Type[BaseProcessor]:
        for t in types:
            key = t.lower().lstrip(".")
            _REGISTRY[key] = cls
            logger.debug("Registered processor %s for type %s", cls.__name__, key)
        return cls

    return decorator


def get_processor_class(doc_type: str) -> Type[BaseProcessor]:
    """Return the processor class for a given document type."""
    key = doc_type.lower().lstrip(".")
    if key not in _REGISTRY:
        from edocapi.exceptions import UnsupportedFileType

        raise UnsupportedFileType(
            f"No processor registered for document type '{doc_type}'.",
            extension=key,
        )
    return _REGISTRY[key]


def list_supported_types() -> list[str]:
    """Return a sorted list of currently supported input types."""
    return sorted(_REGISTRY.keys())
