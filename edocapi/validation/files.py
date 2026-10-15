"""Secure file validation for eDocAPI (magic-byte + extension checks)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

from edocapi.exceptions import (
    FileTooLarge,
    InvalidDocument,
    SecurityError,
    UnsupportedFileType,
    ValidationError,
)
from edocapi.storage.temporary import safe_filename

logger = logging.getLogger("edocapi.validation")

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

# Magic byte signatures (first few bytes)
MAGIC_SIGNATURES: dict[bytes, str] = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "zip",  # DOCX is a ZIP; further checks needed
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"RIFF": "webp",  # needs further check for WEBP
}


def detect_type_from_bytes(data: bytes) -> str | None:
    """Detect document type from magic bytes and light heuristics."""
    if not data:
        return None

    for sig, kind in MAGIC_SIGNATURES.items():
        if data.startswith(sig):
            if kind == "zip":
                # DOCX contains word/ or [Content_Types].xml
                head = data[:8192]
                if b"word/" in head or b"[Content_Types].xml" in head:
                    return "docx"
                return "zip"
            if kind == "webp":
                if b"WEBP" in data[8:16]:
                    return "webp"
                return None
            return kind

    # Text-based heuristics
    try:
        sample = data[:2048].decode("utf-8", errors="ignore").strip().lower()
    except Exception:
        return None

    if sample.startswith("<!doctype html") or sample.startswith("<html") or sample.startswith("<head"):
        return "html"
    if sample.startswith("# ") or sample.startswith("---\n") or sample.startswith("---\r\n"):
        return "markdown"
    # Mostly printable → treat as plain text
    if all(32 <= b < 127 or b in (9, 10, 13) for b in data[:512]):
        return "txt"
    return None


def validate_extension(filename: str) -> str:
    """Validate and return the normalized extension (including leading dot)."""
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
        raise FileTooLarge(
            f"File size {size} bytes exceeds the limit of {max_size} bytes.",
            size=size,
            limit=max_size,
        )


def _extension_to_type(ext: str) -> str:
    mapping = {
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
    return mapping.get(ext.lower(), "unknown")


def validate_file(
    path: Path | str,
    *,
    max_size: int = 50 * 1024 * 1024,
    strict_magic: bool = True,
) -> str:
    """Validate a file on disk and return its normalized type string.

    Performs:
    - existence check
    - size limit
    - extension whitelist
    - magic-byte verification (when strict_magic=True)
    """
    path = Path(path)
    if not path.is_file():
        raise InvalidDocument(f"File does not exist or is not a regular file: {path}")

    size = path.stat().st_size
    if size == 0:
        raise InvalidDocument("File is empty.")
    validate_size(size, max_size)

    ext = validate_extension(path.name)
    declared = _extension_to_type(ext)

    if strict_magic:
        with path.open("rb") as f:
            head = f.read(8192)
        detected = detect_type_from_bytes(head)

        # Allow text formats that may not have strong magic
        text_types = {"html", "markdown", "txt"}
        if detected is None and declared in text_types:
            detected = declared

        if detected is None:
            raise SecurityError(
                f"Could not determine file type from content for '{path.name}'. "
                "Possible unsupported or malicious content."
            )

        # Mismatch is a security risk (e.g. .pdf that is actually executable)
        if detected != declared and not (
            (declared == "jpeg" and detected == "jpeg")
            or (declared in text_types and detected in text_types)
        ):
            # Special case: .docx is detected as "docx", declared as "docx"
            if not (declared == "docx" and detected == "docx"):
                logger.warning(
                    "Type mismatch for %s: extension claims %s, magic claims %s",
                    path.name, declared, detected,
                )
                raise SecurityError(
                    f"File content does not match extension. "
                    f"Extension indicates '{declared}', content indicates '{detected}'."
                )

        return detected

    return declared
