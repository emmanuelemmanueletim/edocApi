"""eDocAPI exception hierarchy."""

from __future__ import annotations


class EdocAPIError(Exception):
    """Base exception for all eDocAPI errors."""

    def __init__(self, message: str = "An error occurred in eDocAPI.") -> None:
        self.message = message
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
        }


class UnsupportedFileType(EdocAPIError):
    """Raised when the uploaded or provided file type is not supported."""

    def __init__(
        self,
        message: str = "The uploaded file type is not supported.",
        *,
        mime_type: str | None = None,
        extension: str | None = None,
    ) -> None:
        if mime_type or extension:
            details = []
            if mime_type:
                details.append(f"MIME type: {mime_type}")
            if extension:
                details.append(f"extension: {extension}")
            message = f"{message} ({', '.join(details)})"
        super().__init__(message)
        self.mime_type = mime_type
        self.extension = extension


class InvalidDocument(EdocAPIError):
    """Raised when a file cannot be parsed as a valid document."""

    def __init__(self, message: str = "The file is not a valid document.") -> None:
        super().__init__(message)


class FileTooLarge(EdocAPIError):
    """Raised when an uploaded file exceeds the configured size limit."""

    def __init__(
        self,
        message: str = "The uploaded file exceeds the maximum allowed size.",
        *,
        size: int | None = None,
        max_size: int | None = None,
    ) -> None:
        if size is not None and max_size is not None:
            message = (
                f"File size {size} bytes exceeds maximum allowed size "
                f"of {max_size} bytes."
            )
        super().__init__(message)
        self.size = size
        self.max_size = max_size


class FileNotFound(EdocAPIError):
    """Raised when a required file cannot be found."""

    def __init__(self, message: str = "The requested file was not found.") -> None:
        super().__init__(message)


class ConversionError(EdocAPIError):
    """Raised when a document conversion fails."""

    def __init__(
        self,
        message: str = "Document conversion failed.",
        *,
        source: str | None = None,
        target: str | None = None,
    ) -> None:
        if source and target:
            message = f"Failed to convert from {source} to {target}: {message}"
        super().__init__(message)
        self.source = source
        self.target = target


class ProcessingError(EdocAPIError):
    """Raised when a document processing operation fails."""

    def __init__(self, message: str = "Document processing failed.") -> None:
        super().__init__(message)


class ValidationError(EdocAPIError):
    """Raised when file or input validation fails."""

    def __init__(self, message: str = "Validation failed.") -> None:
        super().__init__(message)
