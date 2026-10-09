"""File validation utilities for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

from edocapi.exceptions import (
    FileTooLarge,
    InvalidDocument,
    UnsupportedFileType,
    ValidationError,
)

logger = logging.getLogger("edocapi.validation")

# Supported formats for v0.0.1
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".txt",
}

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/html",
    "text/markdown",
    "text/x-markdown",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
}

# Magic byte signatures (first few bytes)
MAGIC_SIGNATURES: dict[bytes, str] = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "zip",  # DOCX is a ZIP; further checks needed
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"RIFF": "webp",  # needs further check for WEBP
}


def detect_type_from_bytes(data: bytes) -> str | None:
    """Attempt to detect document type from magic bytes."""
    if not data:
        return None

    for sig, kind in MAGIC_SIGNATURES.items():
        if data.startswith(sig):
            if kind == "zip":
                # Could be DOCX or other Office format
                if b"word/" in data[:4096] or b"[Content_Types].xml" in data[:4096]:
                    return "docx"
                return "zip"
            if kind == "webp":
                if b"WEBP" in data[8:16]:
                    return "webp"
                return None
            return kind

    # HTML / Markdown / TXT heuristics
    sample = data[:1024].decode("utf-8", errors="ignore").strip().lower()
    if sample.startswith("<!doctype html") or sample.startswith("<html"):
        return "html"
    if sample.startswith("# ") or sample.startswith("---\n"):
        return "markdown"
    # Plain text fallback only if mostly printable
    if all(32 <= b < 127 or b in (9, 10, 13) for b in data[:512]):
        return "txt"
    return None


def validate_extension(filename: str) -> str:
    """Validate and return the normalized extension (including dot)."""
    from edocapi.storage.temporary import safe_filename

    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"File extension '{ext}' is not supported.",
            extension=ext,
        )
    return ext


def validate_size(size: int, max_size: int) -> None:
    """Raise FileTooLarge if size exceeds the limit."""
    if size > max_size:
        raise FileTooLarge(size=size, max_size=max_size)


def validate_file(
    path: Path,
    *,
    max_size: int,
    expected_type: str | None = None,
) -> str:
    """Perform basic validation on a file path.

    Returns the detected document type string (e.g. 'pdf', 'docx').
    """
    if not path.exists():
        raise ValidationError(f"File does not exist: {path}")
    if not path.is_file():
        raise ValidationError(f"Path is not a regular file: {path}")

    size = path.stat().st_size
    validate_size(size, max_size)

    # Read a small header for magic detection
    with path.open("rb") as f:
        header = f.read(4096)

    detected = detect_type_from_bytes(header)
    ext = path.suffix.lower()

    # Map extension to type
    ext_to_type = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".html": "html",
        ".htm": "html",
        ".md": "markdown",
        ".markdown": "markdown",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".png": "png",
        ".webp": "webp",
        ".txt": "txt",
    }
    ext_type = ext_to_type.get(ext)

    if detected is None and ext_type is None:
        raise UnsupportedFileType(
            "Unable to determine file type.",
            extension=ext,
        )

    # Prefer detected type; fall back to extension
    doc_type = detected or ext_type

    # Basic consistency check
    if detected and ext_type and detected != ext_type:
        # Allow some flexibility (e.g. .txt that looks like markdown)
        if not (detected in ("txt", "markdown") and ext_type in ("txt", "markdown")):
            logger.warning(
                "Magic type %s does not match extension type %s for %s",
                detected,
                ext_type,
                path.name,
            )

    if expected_type and doc_type != expected_type:
        raise InvalidDocument(
            f"Expected document type '{expected_type}', got '{doc_type}'."
        )

    return doc_type  # type: ignore[return-value]


def validate_upload(
    filename: str | None,
    content: bytes | BinaryIO,
    *,
    max_size: int,
) -> tuple[str, bytes]:
    """Validate an uploaded file and return (safe_filename, content_bytes)."""
    from edocapi.storage.temporary import safe_filename

    if not filename:
        raise ValidationError("Uploaded file has no filename.")

    safe_name = safe_filename(filename)
    validate_extension(safe_name)

    if hasattr(content, "read"):
        data = content.read()
    else:
        data = content

    if not isinstance(data, (bytes, bytearray)):
        raise ValidationError("File content must be bytes.")

    validate_size(len(data), max_size)

    detected = detect_type_from_bytes(data)
    if detected is None:
        # Still allow based on extension for text formats
        ext = Path(safe_name).suffix.lower()
        if ext not in {".txt", ".md", ".markdown", ".html", ".htm"}:
            raise UnsupportedFileType(
                "Unable to determine a supported file type from content.",
                extension=ext,
            )

    return safe_name, bytes(data)
