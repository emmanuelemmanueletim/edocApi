"""
eDocAPI - A lightweight Python framework for building document-processing
and document-automation APIs.

Simple API for the developer. Powerful document processing underneath.

Author: EMMANUEL EMMANUEL ETIM <emmanuel224etim089@gmail.com>
Repository: https://github.com/emmanuelemmanueletim/edocApi
"""

__version__ = "0.0.1"
__author__ = "EMMANUEL EMMANUEL ETIM"
__author_email__ = "emmanuel224etim089@gmail.com"
__license__ = "MIT"
__copyright__ = "Copyright (c) 2026 EMMANUEL EMMANUEL ETIM"
__url__ = "https://github.com/emmanuelemmanueletim/edocApi"

from edocapi.app import App
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
)
from edocapi.responses import FileResponse, JSONResponse

# Ensure processors are registered on import
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
    "__version__",
]
