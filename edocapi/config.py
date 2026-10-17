"""Configuration for eDocAPI applications."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
"""Largest upload accepted by an eDocAPI application: 50 MiB."""


def _parse_size(value: str | int) -> int:
    """Parse a human-readable size string (e.g. '10MB', '512KB') into bytes."""
    if isinstance(value, int):
        return value
    value = str(value).strip().upper()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMGT]?B?)", value)
    if not match:
        raise ValueError(f"Invalid size specification: {value!r}")
    number = float(match.group(1))
    unit = match.group(2) or "B"
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
    }
    if unit not in multipliers:
        raise ValueError(f"Unknown size unit: {unit}")
    return int(number * multipliers[unit])


@dataclass
class Config:
    """Runtime configuration for an eDocAPI App instance."""

    debug: bool = False
    max_file_size: int = MAX_FILE_SIZE_BYTES
    max_files: int = 20
    max_request_size: int = 100 * 1024 * 1024
    temp_dir: str | None = None
    enable_dashboard: bool = True
    # Security
    strict_magic_check: bool = True
    allowed_extensions: set[str] = field(
        default_factory=lambda: {
            ".pdf", ".docx", ".html", ".htm", ".md", ".markdown",
            ".jpg", ".jpeg", ".png", ".webp", ".txt",
        }
    )
    # ML / OCR (optional)
    enable_ocr: bool = False
    ocr_lang: str = "eng"

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "Config":
        debug = bool(kwargs.get("debug", False))
        max_file_size = _parse_size(kwargs.get("max_file_size", "50MB"))
        max_files = int(kwargs.get("max_files", 20))
        max_request_size = _parse_size(kwargs.get("max_request_size", "100MB"))
        if max_file_size <= 0:
            raise ValueError("max_file_size must be greater than zero.")
        if max_file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError("max_file_size cannot exceed the framework limit of 50MB.")
        if max_files <= 0:
            raise ValueError("max_files must be greater than zero.")
        if max_request_size <= 0:
            raise ValueError("max_request_size must be greater than zero.")
        temp_dir = kwargs.get("temp_dir") or os.environ.get("EDOCAPI_TEMP_DIR")
        enable_dashboard = bool(kwargs.get("dashboard", True))
        strict_magic_check = bool(kwargs.get("strict_magic_check", True))
        enable_ocr = bool(kwargs.get("enable_ocr", False))
        ocr_lang = str(kwargs.get("ocr_lang", "eng"))
        configured_extensions = kwargs.get("allowed_extensions")
        allowed_extensions = (
            {
                str(ext).lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
                for ext in configured_extensions
            }
            if configured_extensions is not None
            else {
                ".pdf", ".docx", ".html", ".htm", ".md", ".markdown",
                ".jpg", ".jpeg", ".png", ".webp", ".txt",
            }
        )
        return cls(
            debug=debug,
            max_file_size=max_file_size,
            max_files=max_files,
            max_request_size=max_request_size,
            temp_dir=temp_dir,
            enable_dashboard=enable_dashboard,
            strict_magic_check=strict_magic_check,
            allowed_extensions=allowed_extensions,
            enable_ocr=enable_ocr,
            ocr_lang=ocr_lang,
        )
