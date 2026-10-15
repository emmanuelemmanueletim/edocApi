"""Custom exceptions for eDocAPI."""

from __future__ import annotations

from typing import Any


class EdocAPIError(Exception):
    """Base exception for all eDocAPI errors."""

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"error": self.__class__.__name__, "message": self.message}
        if self.details is not None:
            d["details"] = self.details
        return d


class UnsupportedFileType(EdocAPIError):
    """Raised when a file type / extension is not supported."""

    def __init__(self, message: str, *, extension: str | None = None) -> None:
        super().__init__(message, details={"extension": extension} if extension else None)
        self.extension = extension


class InvalidDocument(EdocAPIError):
    """Raised when a document is corrupt, empty, or unreadable."""


class FileTooLarge(EdocAPIError):
    """Raised when an uploaded or opened file exceeds the configured size limit."""

    def __init__(self, message: str, *, size: int | None = None, limit: int | None = None) -> None:
        super().__init__(
            message,
            details={"size": size, "limit": limit} if size is not None else None,
        )
        self.size = size
        self.limit = limit


class FileNotFound(EdocAPIError):
    """Raised when a required file path does not exist."""


class ConversionError(EdocAPIError):
    """Raised when a document conversion fails."""


class ProcessingError(EdocAPIError):
    """Raised for general processing failures (merge, compress, etc.)."""


class ValidationError(EdocAPIError):
    """Raised when input validation fails."""


class SecurityError(EdocAPIError):
    """Raised when a security policy is violated (path traversal, unsafe content, etc.)."""
