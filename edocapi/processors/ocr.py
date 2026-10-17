"""Helpers shared by image and PDF OCR processors."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def normalize_tesseract_language(lang: str) -> str:
    """Accept common English aliases while keeping Tesseract's ``eng`` code."""
    aliases = {"en": "eng", "en-us": "eng", "en-gb": "eng"}
    return "+".join(aliases.get(part.strip().casefold(), part.strip())
                    for part in lang.split("+") if part.strip())


def configure_tesseract(pytesseract: Any) -> None:
    """Locate the Tesseract executable when it is missing from the process PATH.

    ``TESSERACT_CMD`` can point to a custom executable. On Windows, also check
    the default install folders used by the UB Mannheim installer.
    """
    command = pytesseract.pytesseract.tesseract_cmd
    if shutil.which(command):
        return

    candidates = [os.environ.get("TESSERACT_CMD")]
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates.append(str(Path(root) / "Tesseract-OCR" / "tesseract.exe"))

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def find_poppler_bin() -> str | None:
    """Find a Poppler bin folder, including the common Windows WinGet install."""
    configured = os.environ.get("POPPLER_PATH")
    if configured:
        return configured

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            matches = sorted(packages.glob(
                "oschwartz10612.Poppler_*/poppler-*/Library/bin"
            ))
            for candidate in reversed(matches):
                if (candidate / "pdfinfo.exe").is_file() and (candidate / "pdftoppm.exe").is_file():
                    return str(candidate)
    return None
