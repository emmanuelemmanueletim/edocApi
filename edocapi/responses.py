"""Response helpers for eDocAPI."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Mapping

from starlette.responses import FileResponse as StarletteFileResponse
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.responses import Response


class JSONResponse(StarletteJSONResponse):
    """JSON response that serializes normal Python dicts / lists."""

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            content=content if content is not None else {},
            status_code=status_code,
            headers=headers,
            **kwargs,
        )


class FileResponse(StarletteFileResponse):
    """File response with sensible defaults for document downloads.

    Automatically sets Content-Type and Content-Disposition when possible.
    """

    def __init__(
        self,
        path: str | Path,
        filename: str | None = None,
        media_type: str | None = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        background: Any = None,
        **kwargs: Any,
    ) -> None:
        path = Path(path)
        if filename is None:
            filename = path.name

        if media_type is None:
            guessed, _ = mimetypes.guess_type(filename)
            media_type = guessed or "application/octet-stream"

        super().__init__(
            path=str(path),
            filename=filename,
            media_type=media_type,
            status_code=status_code,
            headers=headers,
            background=background,
            **kwargs,
        )


def make_error_response(
    error: Exception,
    *,
    status_code: int = 400,
    debug: bool = False,
) -> JSONResponse:
    """Create a consistent JSON error response from an exception."""
    from edocapi.exceptions import EdocAPIError

    if isinstance(error, EdocAPIError):
        body = error.to_dict()
        if debug:
            body["detail"] = str(error)
    else:
        body = {
            "error": type(error).__name__,
            "message": str(error) if debug else "An unexpected error occurred.",
        }
        if debug:
            body["detail"] = str(error)

    return JSONResponse(content=body, status_code=status_code)
