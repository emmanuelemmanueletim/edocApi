"""Temporary file management for eDocAPI."""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("edocapi.storage")


class TemporaryStorage:
    """Manages a private temporary directory for document processing.

    Files created here are cleaned up when the storage instance is closed
    or when the process exits (via atexit).
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is not None:
            self._root = Path(base_dir)
            self._root.mkdir(parents=True, exist_ok=True)
            self._owned = False
        else:
            self._root = Path(tempfile.mkdtemp(prefix="edocapi_"))
            self._owned = True

        self._files: set[Path] = set()
        atexit.register(self.cleanup)
        logger.debug("Temporary storage created at %s", self._root)

    @property
    def root(self) -> Path:
        return self._root

    def create_file(
        self,
        suffix: str = "",
        prefix: str = "tmp_",
        content: bytes | None = None,
    ) -> Path:
        """Create a new temporary file path (and optionally write content)."""
        name = f"{prefix}{uuid.uuid4().hex}{suffix}"
        path = self._root / name
        if content is not None:
            path.write_bytes(content)
        else:
            path.touch()
        self._files.add(path)
        return path

    def create_dir(self, prefix: str = "dir_") -> Path:
        """Create a subdirectory inside the temporary root."""
        name = f"{prefix}{uuid.uuid4().hex}"
        path = self._root / name
        path.mkdir(parents=True, exist_ok=True)
        self._files.add(path)
        return path

    def register(self, path: Path | str) -> Path:
        """Register an existing path for later cleanup."""
        path = Path(path)
        self._files.add(path)
        return path

    def cleanup(self) -> None:
        """Remove all tracked files and, if owned, the root directory."""
        for path in list(self._files):
            try:
                if path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except OSError as exc:
                logger.warning("Failed to clean up %s: %s", path, exc)
        self._files.clear()

        if self._owned and self._root.exists():
            try:
                shutil.rmtree(self._root, ignore_errors=True)
                logger.debug("Removed temporary root %s", self._root)
            except OSError as exc:
                logger.warning("Failed to remove temp root %s: %s", self._root, exc)

    def __enter__(self) -> "TemporaryStorage":
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()

    def __del__(self) -> None:
        try:
            self.cleanup()
        except Exception:
            pass


def safe_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal and unsafe characters."""
    # Take only the basename
    name = os.path.basename(name)
    # Remove null bytes and control characters
    name = "".join(c for c in name if c.isprintable() and c not in r'<>:"/\|?*')
    name = name.strip().strip(".")
    if not name:
        name = "unnamed"
    # Limit length
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[:190] + ext
    return name
