"""eDocAPI provides document processing tools and an ASGI application for Python."""

from __future__ import annotations

__version__ = "0.1.1"
__author__ = "EMMANUEL EMMANUEL ETIM"

from edocapi.document import Document
from edocapi.exceptions import (
    EdocAPIError,
    UnsupportedFileType,
    InvalidDocument,
    FileTooLarge,
    FileNotFound,
    ConversionError,
    ProcessingError,
    ValidationError,
    SecurityError,
)
from edocapi.responses import FileResponse, JSONResponse
from edocapi.app import App

# Register built-in processors on import
import edocapi.processors  # noqa: F401

__all__ = [
    "App",
    "Document",
    "FileResponse",
    "JSONResponse",
    "EdocAPIError",
    "UnsupportedFileType",
    "InvalidDocument",
    "FileTooLarge",
    "FileNotFound",
    "ConversionError",
    "ProcessingError",
    "ValidationError",
    "SecurityError",
    "__version__",
]
