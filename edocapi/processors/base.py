"""Base processor and registry for eDocAPI document processors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Type

logger = logging.getLogger("edocapi.processors")

_REGISTRY: dict[str, Type["BaseProcessor"]] = {}


class BaseProcessor(ABC):
    """Abstract base class for format-specific document processors."""

    supported_input_types: set[str] = set()
    supported_output_types: set[str] = set()

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        self.path = Path(path)
        self.temp_storage = temp_storage

    def _temp_path(self, *, suffix: str = "", prefix: str = "out_") -> Path:
        if self.temp_storage is not None:
            return self.temp_storage.create_file(suffix=suffix, prefix=prefix)
        import tempfile
        fd, name = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        import os
        os.close(fd)
        return Path(name)

    @abstractmethod
    def to_pdf(self) -> Path:
        ...

    def to_text(self) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support text extraction."
        )

    def to_html(self) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support HTML conversion."
        )

    def to_images(self, *, format: str = "png") -> list[Path]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support image conversion."
        )

    def info(self) -> dict[str, Any]:
        stat = self.path.stat()
        return {
            "filename": self.path.name,
            "type": next(iter(self.supported_input_types), "unknown"),
            "size": stat.st_size,
            "extension": self.path.suffix.lower(),
        }

    def extract_text(self) -> str:
        return self.to_text()


def register_processor(*types: str):
    """Decorator to register a processor for one or more input types."""

    def decorator(cls: Type[BaseProcessor]) -> Type[BaseProcessor]:
        for t in types:
            key = t.lower().lstrip(".")
            _REGISTRY[key] = cls
            logger.debug("Registered processor %s for type %s", cls.__name__, key)
        return cls

    return decorator


def get_processor_class(doc_type: str) -> Type[BaseProcessor]:
    key = doc_type.lower().lstrip(".")
    if key not in _REGISTRY:
        from edocapi.exceptions import UnsupportedFileType
        raise UnsupportedFileType(
            f"No processor registered for document type '{doc_type}'.",
            extension=key,
        )
    return _REGISTRY[key]


def list_supported_types() -> list[str]:
    return sorted(_REGISTRY.keys())
