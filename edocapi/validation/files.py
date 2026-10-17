"""Secure file validation for eDocAPI (magic-byte + extension checks)."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from edocapi.exceptions import (
    FileTooLarge,
    InvalidDocument,
    SecurityError,
    UnsupportedFileType,
)
from edocapi.config import MAX_FILE_SIZE_BYTES
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
    b"%PDF-": "pdf",
    b"PK\x03\x04": "zip",
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

    # Text formats have no fixed magic signature. Require valid UTF-8 and
    # reject binary control characters rather than trusting the extension.
    try:
        decoded = data[:8192].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not decoded or any(ord(char) < 32 and char not in "\t\r\n\f" for char in decoded):
        return None
    sample = decoded.lstrip("\ufeff \t\r\n").lower()
    if sample.startswith(("<!doctype html", "<html", "<head", "<body")):
        return "html"
    if sample.startswith(("# ", "---\n", "---\r\n")):
        return "markdown"
    if all(char.isprintable() or char in "\t\r\n\f" for char in decoded):
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
    max_size: int = MAX_FILE_SIZE_BYTES,
    strict_magic: bool = True,
    allowed_extensions: set[str] | None = None,
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
        raise InvalidDocument("File does not exist or is not a regular file.")

    size = path.stat().st_size
    if size == 0:
        raise InvalidDocument("File is empty.")
    validate_size(size, max_size)

    ext = Path(safe_filename(path.name)).suffix.lower()
    permitted = SUPPORTED_EXTENSIONS if allowed_extensions is None else {
        item.lower() if item.startswith(".") else f".{item.lower()}"
        for item in allowed_extensions
    }
    if ext not in permitted or ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"File extension '{ext}' is not supported or allowed.", extension=ext
        )
    declared = _extension_to_type(ext)

    if strict_magic:
        with path.open("rb") as f:
            head = f.read(8192)
        detected = detect_type_from_bytes(head)

        # Text files have no fixed signature; validate their content as text.
        text_types = {"html", "markdown", "txt"}
        if detected is None and declared in text_types:
            raise SecurityError("File content is not valid text for its declared type.")

        if detected is None:
            raise SecurityError(
                "Could not determine file type from content; the file may be unsupported or malformed."
            )

        if declared == "docx":
            try:
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
                    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                        raise SecurityError("DOCX package is missing required document components.")
                    if archive.testzip() is not None:
                        raise SecurityError("DOCX package contains a corrupted component.")
            except SecurityError:
                raise
            except Exception as exc:
                raise SecurityError("DOCX content is not a valid Office document package.") from exc

        # Mismatch is a security risk (e.g. .pdf that is actually executable)
        if detected != declared and not (declared == "jpeg" and detected == "jpeg"):
            # Special case: .docx is detected as "docx", declared as "docx"
            if not (declared == "docx" and detected == "docx"):
                logger.warning(
                    "Type mismatch for %s: extension claims %s, magic claims %s",
                    path.name, declared, detected,
                )
                raise SecurityError(
                    "File content does not match its declared extension."
                )

        return detected

    return declared
