"""HTTP Request interface used by the eDocAPI ASGI application."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import parse_qs

from edocapi.exceptions import FileTooLarge


class Request:
    """Lightweight request object built from an ASGI scope + receive."""

    def __init__(
        self,
        scope: dict,
        receive: Any,
        body: bytes | None = None,
        *,
        max_body_size: int | None = None,
    ) -> None:
        self.scope = scope
        self._receive = receive
        self._body = body
        self._max_body_size = max_body_size
        self.method = scope.get("method", "GET").upper()
        self.path = scope.get("path", "/")
        self.query_string = scope.get("query_string", b"").decode("latin-1")
        self.headers: dict[str, str] = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        self.path_params: dict[str, str] = {}
        self._form: dict[str, Any] | None = None
        self._query: dict[str, str] | None = None

    @property
    def query_params(self) -> Mapping[str, str]:
        if self._query is None:
            qs = parse_qs(self.query_string, keep_blank_values=True)
            self._query = {k: v[-1] if v else "" for k, v in qs.items()}
        return self._query

    async def body(self, max_size: int | None = None) -> bytes:
        if self._max_body_size is not None:
            max_size = min(max_size, self._max_body_size) if max_size is not None else self._max_body_size
        content_length = self.headers.get("content-length")
        if max_size is not None and content_length and content_length.isdigit() and int(content_length) > max_size:
            raise FileTooLarge("Request body exceeds the configured limit.", size=int(content_length), limit=max_size)
        if self._body is not None:
            if max_size is not None and len(self._body) > max_size:
                raise FileTooLarge("Request body exceeds the configured limit.", size=len(self._body), limit=max_size)
            return self._body
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await self._receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                size += len(chunk)
                if max_size is not None and size > max_size:
                    raise FileTooLarge("Request body exceeds the configured limit.", size=size, limit=max_size)
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break
        self._body = b"".join(chunks)
        return self._body

    async def json(self) -> Any:
        data = await self.body()
        return json.loads(data.decode("utf-8"))

    async def form(self) -> Mapping[str, Any]:
        """Return already-parsed form data (populated by the App)."""
        return self._form or {}
