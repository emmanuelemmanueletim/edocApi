"""Lightweight response objects (framework-independent)."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote
from edocapi.storage.temporary import safe_filename


class JSONResponse:
    """JSON HTTP response."""

    def __init__(
        self,
        content: Any,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.headers.setdefault("content-type", "application/json; charset=utf-8")

    def body(self) -> bytes:
        return json.dumps(self.content, ensure_ascii=False, default=str).encode("utf-8")


class FileResponse:
    """File download response."""

    def __init__(
        self,
        path: Path | str,
        *,
        filename: str | None = None,
        media_type: str | None = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        background: Callable[[], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self.filename = safe_filename(filename or self.path.name)
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.background = background

        if media_type is None:
            media_type, _ = mimetypes.guess_type(str(self.path))
            media_type = media_type or "application/octet-stream"
        self.media_type = media_type
        self.headers.setdefault("content-type", media_type)
        # Force download
        self.headers.setdefault(
            "content-disposition",
            f"attachment; filename=\"{self.filename.encode('ascii', errors='ignore').decode('ascii') or 'download'}\"; filename*=UTF-8''{quote(self.filename, safe='')}",
        )

    def body(self) -> bytes:
        return self.path.read_bytes()


def make_error_response(
    exc: Exception,
    *,
    status_code: int = 400,
    debug: bool = False,
) -> JSONResponse:
    """Build a consistent JSON error response."""
    from edocapi.exceptions import EdocAPIError

    if isinstance(exc, EdocAPIError):
        payload = exc.to_dict()
    else:
        payload = {
            "error": exc.__class__.__name__,
            "message": str(exc) if debug else "An internal error occurred.",
        }
    if debug and not isinstance(exc, EdocAPIError):
        import traceback
        payload["traceback"] = traceback.format_exc()
    return JSONResponse(payload, status_code=status_code)
