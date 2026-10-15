"""Secure temporary file storage for eDocAPI."""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger("edocapi.storage")


def safe_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal and unsafe characters.

    Security measures:
    - Only the basename is kept
    - Null bytes and control characters are stripped
    - Characters that are dangerous on Windows/Unix are removed
    - Length is limited
    - Empty results become "unnamed"
    """
    # Take only the basename (blocks ../ attacks)
    name = os.path.basename(name)
    # Remove null bytes and non-printable characters
    name = "".join(c for c in name if c.isprintable() and c not in r'<>:"/\|?*\0')
    name = name.strip().strip(".")
    if not name:
        name = "unnamed"
    # Limit length while preserving extension
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[:190] + ext
    return name


class TemporaryStorage:
    """Manages a private temporary directory and tracked files.

    Files are cleaned up on explicit ``cleanup()``, context-manager exit,
    or process exit via ``atexit``.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        if root:
            self._root = Path(root)
            self._root.mkdir(parents=True, exist_ok=True)
            self._owned = False
        else:
            self._root = Path(tempfile.mkdtemp(prefix="edocapi_"))
            self._owned = True
        self._root = self._root.resolve()
        self._files: set[Path] = set()
        self._cleanup_callback = self.cleanup
        atexit.register(self._cleanup_callback)
        logger.debug("TemporaryStorage root: %s (owned=%s)", self._root, self._owned)

    @property
    def root(self) -> Path:
        return self._root

    def create_file(
        self,
        *,
        suffix: str = "",
        prefix: str = "tmp_",
        content: bytes | None = None,
    ) -> Path:
        """Create a new temporary file inside the managed root."""
        safe_suffix = "".join(c for c in suffix if c.isalnum() or c in "._-")[:32]
        safe_prefix = "".join(c for c in prefix if c.isalnum() or c in "._-")[:40] or "tmp_"
        path = self._root / f"{safe_prefix}{uuid.uuid4().hex}{safe_suffix}"
        try:
            with path.open("xb") as handle:
                if content is not None:
                    handle.write(content)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self._files.add(path)
        return path

    def create_dir(self, *, prefix: str = "dir_") -> Path:
        """Create a temporary subdirectory."""
        safe_prefix = "".join(c for c in prefix if c.isalnum() or c in "._-")[:40] or "dir_"
        name = f"{safe_prefix}{uuid.uuid4().hex}"
        path = self._root / name
        path.mkdir(exist_ok=False)
        self._files.add(path)
        return path

    def register(self, path: Path | str) -> Path:
        """Register an existing path for later cleanup."""
        path = self._managed_path(path)
        self._files.add(path)
        return path

    def _managed_path(self, path: Path | str) -> Path:
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("Temporary storage only manages paths inside its root.") from exc
        if resolved == self._root:
            raise ValueError("Temporary storage root cannot be registered or removed.")
        return resolved

    def discard(self, path: Path | str) -> None:
        """Remove a file from managed storage after its response is sent."""
        try:
            path = self._managed_path(path)
        except ValueError:
            logger.warning("Refusing to remove path outside temporary storage: %s", path)
            return
        if path not in self._files:
            logger.warning("Refusing to remove unregistered temporary path: %s", path)
            return
        self._files.discard(path)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove temporary file %s: %s", path, exc)

    def cleanup(self) -> None:
        """Remove all tracked files and, if owned, the root directory."""
        for path in list(self._files):
            try:
                path = self._managed_path(path)
                if path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except (OSError, ValueError) as exc:
                logger.warning("Failed to clean up %s: %s", path, exc)
        self._files.clear()

        if self._owned and self._root.exists():
            try:
                shutil.rmtree(self._root, ignore_errors=True)
                logger.debug("Removed temporary root %s", self._root)
            except OSError as exc:
                logger.warning("Failed to remove temp root %s: %s", self._root, exc)

        try:
            atexit.unregister(self._cleanup_callback)
        except Exception:
            pass

    def __enter__(self) -> "TemporaryStorage":
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()

    def __del__(self) -> None:
        try:
            self.cleanup()
        except Exception:
            pass
