"""eDocAPI ASGI application with built-in routing for document workflows."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import mimetypes
import sys
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Sequence

from edocapi.config import Config
from edocapi.exceptions import EdocAPIError, FileTooLarge, InvalidDocument, MissingUpload, SecurityError, UnsupportedFileType, ValidationError
from edocapi.http.multipart import parse_multipart
from edocapi.http.request import Request
from edocapi.responses import FileResponse, JSONResponse, make_error_response
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi")


class Route:
    """Simple route descriptor."""

    __slots__ = ("path", "methods", "endpoint", "name", "pattern", "limit")

    def __init__(
        self,
        path: str,
        endpoint: Callable,
        methods: Sequence[str],
        name: str | None = None,
        limit: tuple[int, float] | None = None,
    ) -> None:
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or "?" in path
            or "#" in path
            or "\\" in path
            or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in path)
        ):
            raise ValueError("Route paths must be absolute URL paths without query, fragment, or backslash characters.")
        names = re.findall(r"\{([^{}]+)\}", path)
        if any(not re.fullmatch(r"[A-Za-z_]\w*", name) for name in names) or len(names) != len(set(names)):
            raise ValueError("Route parameters must use unique identifier placeholders such as '/items/{item_id}'.")
        placeholders = list(re.finditer(r"\{([A-Za-z_]\w*)\}", path))
        if "{" in re.sub(r"\{[A-Za-z_]\w*\}", "", path) or "}" in re.sub(r"\{[A-Za-z_]\w*\}", "", path):
            raise ValueError("Malformed route parameter placeholder.")
        self.path = path
        self.methods = {m.upper() for m in methods}
        if not self.methods or any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Z-]+", method) for method in self.methods):
            raise ValueError("Routes require valid HTTP method names.")
        self.endpoint = endpoint
        self.name = name or endpoint.__name__
        self.limit = limit
        pattern = ""
        cursor = 0
        for placeholder in placeholders:
            pattern += re.escape(path[cursor:placeholder.start()])
            pattern += f"(?P<{placeholder.group(1)}>[^/]+)"
            cursor = placeholder.end()
        pattern += re.escape(path[cursor:])
        self.pattern = re.compile(f"^{pattern}$")


class App:
    """Main eDocAPI application (pure ASGI).

    Example::

        from edocapi import App, Document

        app = App()

        @app.post("/convert")
        def convert(file):
            return Document(file).to_pdf()

    The instance itself is a valid ASGI callable::

        # uvicorn myapp:app
        # or
        # hypercorn myapp:app
    """

    def __init__(
        self,
        debug: bool = False,
        max_file_size: str | int = "50MB",
        temp_dir: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.config = Config.from_kwargs(
            debug=debug,
            max_file_size=max_file_size,
            temp_dir=temp_dir,
            **kwargs,
        )
        self._routes: list[Route] = []
        self._global_limit: tuple[int, float] | None = None
        self._rate_buckets: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._rate_lock = threading.Lock()
        self._temp_storage = TemporaryStorage(self.config.temp_dir)

        # Expose a built-in liveness endpoint for deployments that run the
        # package App directly instead of the example routes in main.py.
        self._add_route("/health", self._health_endpoint, ["GET", "POST"], name="health")

        level = logging.DEBUG if self.config.debug else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(levelname)-5s  %(name)s  %(message)s",
        )

        if self.config.enable_dashboard:
            self._add_route("/", self._dashboard_endpoint, ["GET"], name="dashboard")

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def _add_route(
        self,
        path: str,
        endpoint: Callable,
        methods: Sequence[str],
        name: str | None = None,
        limit: str | tuple[int, float] | None = None,
    ) -> None:
        self._routes.append(Route(path, endpoint, methods, name=name, limit=self._parse_route_limit(limit)))

    @staticmethod
    def _parse_limit(value: str | tuple[int, float]) -> tuple[int, float]:
        if isinstance(value, tuple) and len(value) == 2:
            count, seconds = value
        elif isinstance(value, str):
            match = re.fullmatch(r"\s*(\d+)\s*/\s*(second|minute|hour|day)s?\s*", value, re.IGNORECASE)
            if not match:
                raise ValueError("Rate limits must look like '10/minute', '20/second', '300/hour', or '1000/day'.")
            count = int(match.group(1))
            seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[match.group(2).lower().rstrip("s")]
        else:
            raise ValueError("Rate limit must be a '<count>/<period>' string or (count, seconds) tuple.")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("Rate limit request count must be a positive integer.")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
            raise ValueError("Rate limit period must be a positive number of seconds.")
        return count, float(seconds)

    @classmethod
    def _parse_route_limit(cls, limit: str | tuple[int, float] | None) -> tuple[int, float] | None:
        return cls._parse_limit(limit) if limit is not None else None

    @staticmethod
    def _period_name(seconds: float) -> str:
        for unit, duration in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
            if seconds == duration:
                return unit
        return f"{seconds:g}s"

    def limits(self, requests: int, *, per: str = "minute") -> "App":
        """Set the default per-client request limit for all routes except health."""
        if isinstance(requests, bool) or not isinstance(requests, int) or requests <= 0:
            raise ValueError("Rate limit request count must be a positive integer.")
        period = self._parse_limit(f"{requests}/{per}")
        self._global_limit = period
        return self

    def get(self, path: str, *, limit: str | tuple[int, float] | None = None) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["GET"], limit=limit)
            return func
        return decorator

    def post(self, path: str, *, limit: str | tuple[int, float] | None = None) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["POST"], limit=limit)
            return func
        return decorator

    def put(self, path: str, *, limit: str | tuple[int, float] | None = None) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["PUT"], limit=limit)
            return func
        return decorator

    def delete(self, path: str, *, limit: str | tuple[int, float] | None = None) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["DELETE"], limit=limit)
            return func
        return decorator

    def route(
        self,
        path: str,
        methods: Sequence[str] | None = None,
        *,
        limit: str | tuple[int, float] | None = None,
    ) -> Callable:
        methods = methods or ["GET"]

        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, methods, limit=limit)
            return func
        return decorator

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def _dashboard_endpoint(self) -> str:
        from importlib.util import find_spec
        from edocapi.document import Document
        from edocapi.dashboard import render_dashboard

        routes = []
        for route in self._routes:
            if route.name == "dashboard":
                continue
            params = []
            for parameter in inspect.signature(route.endpoint).parameters.values():
                if parameter.name == "request":
                    continue
                param_info = {
                    "name": parameter.name,
                    "required": parameter.default is inspect.Parameter.empty,
                    "kind": "upload" if parameter.name in ("file", "files") else "parameter",
                    "multiple": parameter.name == "files",
                    "default": (
                        None if parameter.default is inspect.Parameter.empty
                        else str(parameter.default)
                    ),
                    "type": (
                        getattr(parameter.annotation, "__name__", "string")
                        if parameter.annotation is not inspect.Parameter.empty
                        else "string"
                    ),
                }
                if route.name == "ocr" and parameter.name == "engine":
                    paddle_unavailable = sys.version_info >= (3, 14)
                    if not paddle_unavailable:
                        paddle_unavailable = find_spec("paddleocr") is None
                    param_info["choices"] = [
                        {"value": "tesseract", "label": "Standard OCR (Tesseract)"},
                        {
                            "value": "paddle",
                            "label": "Advanced OCR (layout, tables, formulas)",
                            "disabled": paddle_unavailable,
                        },
                    ]
                    if sys.version_info >= (3, 14):
                        param_info["help"] = (
                            f"PaddleOCR is disabled because this server runs Python "
                            f"{sys.version_info.major}.{sys.version_info.minor}. "
                            "Run the server with Python 3.13 or earlier and install the "
                            "structured-ocr extra to enable advanced OCR."
                        )
                    elif paddle_unavailable:
                        param_info["help"] = (
                            "PaddleOCR is not installed in this server environment. "
                            'Install it with: python -m pip install -e '
                            '".[structured-ocr,server]", then restart the server.'
                        )
                    else:
                        param_info["help"] = (
                            "PDF pages with embedded text skip OCR model startup. For scanned pages, "
                            "prefetching downloads model files. The first OCR request in each server "
                            "process still loads cached weights into memory and may take a while on CPU; "
                            "later requests reuse the loaded pipeline until the server restarts. "
                            "Large chart parsing is optional; see the README to enable it."
                        )
                params.append(param_info)
            routes.append({
                "path": route.path,
                "methods": sorted(route.methods),
                "name": route.name,
                "description": inspect.getdoc(route.endpoint) or "",
                "rate_limit": (
                    f"{route.limit[0]}/{self._period_name(route.limit[1])}"
                    if route.limit is not None
                    else f"{self._global_limit[0]}/{self._period_name(self._global_limit[1])}"
                    if self._global_limit is not None and route.path.rstrip("/").lower() != "/health"
                    else None
                ),
                "parameters": params,
            })
        return render_dashboard(
            routes,
            Document.supported_types(),
            self.config.max_file_size,
        )

    def _health_endpoint(self) -> dict[str, Any]:
        from edocapi import __version__
        from edocapi.document import Document

        return {
            "message": f"eDocAPI v{__version__}",
            "supported_types": Document.supported_types(),
        }

    # ------------------------------------------------------------------
    # ASGI interface
    # ------------------------------------------------------------------

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return

        request = Request(
            scope,
            receive,
            max_body_size=self.config.max_request_size,
        )
        response: Any
        try:
            response = await self._handle(request)
        except FileTooLarge as exc:
            response = make_error_response(exc, status_code=413)
        except EdocAPIError as exc:
            status = 415 if isinstance(exc, (UnsupportedFileType, SecurityError)) else 400
            response = make_error_response(exc, status_code=status)
        except Exception:
            logger.exception("Unhandled ASGI request failure")
            response = make_error_response(RuntimeError(), status_code=500)
        for header, value in getattr(request, "_rate_headers", {}).items():
            response.headers[header] = value
        await self._send_response(response, send)

    async def _handle(self, request: Request) -> Any:
        # Find matching route
        matched: Route | None = None
        path_params: dict[str, str] = {}
        for route in self._routes:
            m = route.pattern.match(request.path)
            if m and request.method in route.methods:
                matched = route
                path_params = m.groupdict()
                break

        if matched is None:
            return JSONResponse(
                {"error": "NotFound", "message": f"No route for {request.method} {request.path}"},
                status_code=404,
            )

        if matched.path.rstrip("/").lower() != "/health":
            limited = self._rate_limit_response(matched, request)
            if limited is not None:
                return limited

        request.path_params = path_params
        return await self._dispatch(matched.endpoint, request, route_path=matched.path)

    def _rate_limit_response(self, route: Route, request: Request) -> JSONResponse | None:
        policies: list[tuple[str, int, float]] = []
        if self._global_limit is not None:
            policies.append(("*", self._global_limit[0], self._global_limit[1]))
        if route.limit is not None:
            policies.append((f"{','.join(sorted(route.methods))}:{route.path}", route.limit[0], route.limit[1]))
        if not policies:
            return None
        client = request.scope.get("client")
        identity = str(client[0]) if isinstance(client, (tuple, list)) and client else "unknown"
        now = time.monotonic()
        with self._rate_lock:
            active: list[tuple[tuple[str, str], deque[float], int, float]] = []
            for policy_key, count, period in policies:
                key = (identity, policy_key)
                bucket = self._rate_buckets.setdefault(key, deque())
                self._rate_buckets.move_to_end(key)
                cutoff = now - period
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                active.append((key, bucket, count, period))
            exceeded = next(
                (item for item in active if len(item[1]) >= item[2]),
                None,
            )
            if exceeded is not None:
                _, bucket, count, period = exceeded
                retry_after = max(1, int(bucket[0] + period - now + 0.999))
                return JSONResponse(
                    {"error": "RateLimitExceeded", "message": "Too many requests. Please retry later."},
                    status_code=429,
                    headers={
                        "retry-after": str(retry_after),
                        "x-ratelimit-limit": str(count),
                        "x-ratelimit-remaining": "0",
                    },
                )
            for _, bucket, _, _ in active:
                bucket.append(now)
            most_restrictive = min(active, key=lambda item: (item[2] - len(item[1])) / item[2])
            _, bucket, count, _ = most_restrictive
            remaining = count - len(bucket)
            request._rate_headers = {
                "x-ratelimit-limit": str(count),
                "x-ratelimit-remaining": str(remaining),
            }
            while len(self._rate_buckets) > 8192:
                self._rate_buckets.popitem(last=False)
        return None

    async def _dispatch(self, endpoint: Callable, request: Request, *, route_path: str = "") -> Any:
        from edocapi.document import Document

        uploads: list = []
        try:
            sig = inspect.signature(endpoint)
            kwargs: dict[str, Any] = {}
            is_ocr_route = (
                route_path.rstrip("/").lower() == "/ocr"
                or (endpoint.__name__ == "ocr" and "engine" in sig.parameters and "lang" in sig.parameters)
            )
            if is_ocr_route and not self.config.enable_ocr:
                raise EdocAPIError("OCR is disabled for this application. Enable it with enable_ocr=True.")

            # Parse multipart when needed
            form_fields: dict[str, str] = {}
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type.lower() and any(
                p in sig.parameters for p in ("file", "files")
            ):
                uploads, form_fields = await parse_multipart(
                    request.iter_body(),
                    content_type,
                    max_size=self.config.max_file_size,
                    max_files=self.config.max_files,
                    temp_storage=self._temp_storage,
                    max_request_size=self.config.max_request_size,
                    content_length=(
                        int(request.headers["content-length"])
                        if request.headers.get("content-length", "").isdigit()
                        else None
                    ),
                )
                request._form = form_fields
                for uploaded in uploads:
                    self._validate_upload(uploaded)

            for name, param in sig.parameters.items():
                if name == "request":
                    kwargs["request"] = request
                elif name == "file":
                    if not uploads:
                        raise MissingUpload("No file uploaded; provide a file field.")
                    kwargs["file"] = uploads[0]
                elif name == "files":
                    if not uploads:
                        raise MissingUpload("No files uploaded; provide one or more files fields.")
                    kwargs["files"] = uploads
                elif name in request.path_params:
                    kwargs[name] = request.path_params[name]
                elif name in form_fields:
                    kwargs[name] = form_fields[name]
                elif name in request.query_params:
                    kwargs[name] = request.query_params[name]
                elif name == "lang" and is_ocr_route:
                    kwargs[name] = self.config.ocr_lang
                elif param.default is not inspect.Parameter.empty:
                    continue
                else:
                    raise ValidationError(f"Required parameter '{name}' was not provided.")

            if inspect.iscoroutinefunction(endpoint):
                result = await endpoint(**kwargs)
            else:
                # OCR, conversions, and other synchronous handlers can take
                # seconds or minutes. Keep them off the ASGI event loop so
                # health checks and the dashboard remain responsive meanwhile.
                result = await asyncio.to_thread(endpoint, **kwargs)

            response = self._make_response(result)

        except EdocAPIError as exc:
            status = 413 if isinstance(exc, FileTooLarge) else 415 if isinstance(exc, (UnsupportedFileType, SecurityError)) else 400
            logger.warning("eDocAPI error: %s", exc)
            response = make_error_response(exc, status_code=status)
        except Exception as exc:
            logger.exception("Unhandled error in endpoint")
            response = make_error_response(exc, status_code=500)

        if uploads:
            previous_background = getattr(response, "background", None)
            response_path = response.path if isinstance(response, FileResponse) else None
            upload_cleanup = [
                self._cleanup_callback(path, self._temp_storage)
                for path in uploads
                if path != response_path
            ]

            def cleanup_request_files() -> None:
                try:
                    if callable(previous_background):
                        previous_background()
                finally:
                    for cleanup in upload_cleanup:
                        cleanup()

            # Defer cleanup until after response bytes are sent. This also
            # supports endpoints that return an uploaded file directly.
            response.background = cleanup_request_files
        return response

    def _validate_upload(self, path: Any) -> None:
        extension = path.suffix.lower()
        allowed = {
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in self.config.allowed_extensions
        }
        if extension not in allowed:
            raise UnsupportedFileType(
                f"File extension '{extension or '(none)'}' is not allowed.",
                extension=extension,
            )
        from edocapi.document import Document
        Document(
            path,
            max_size=self.config.max_file_size,
            strict_magic=self.config.strict_magic_check,
            allowed_extensions=self.config.allowed_extensions,
            temp_storage=self._temp_storage,
        )

    def _make_response(self, result: Any) -> Any:
        from edocapi.document import Document
        from pathlib import Path

        if result is None:
            return JSONResponse({"success": True})

        if isinstance(result, (JSONResponse, FileResponse)):
            return result

        if isinstance(result, Document):
            path = result.path
            headers: dict[str, str] = {}
            compression_mode = getattr(result, "_compression_mode", None)
            if compression_mode:
                headers["X-Edocapi-Compression-Mode"] = compression_mode
            if compression_mode in {"pdf", "image"}:
                target_met = getattr(result, "_compression_target_met", None)
                if target_met is not None:
                    headers["X-Edocapi-Compression-Target-Met"] = str(target_met).lower()
                    headers["X-Edocapi-Compression-Target-Bytes"] = str(
                        result._compression_target_size
                    )
            filename = path.name
            if compression_mode == "image":
                original_name = Path(getattr(result, "_original_name", path.name))
                filename = f"compressed_{original_name.stem}{path.suffix.lower()}"
            return FileResponse(
                path,
                filename=filename,
                headers=headers,
                background=self._cleanup_callback(path, result._temp),
            )

        if isinstance(result, Path):
            return FileResponse(
                result,
                filename=result.name,
                background=self._cleanup_callback(result, self._temp_storage),
            )

        if isinstance(result, (dict, list)):
            return JSONResponse(result)

        if isinstance(result, str):
            # Dashboard returns HTML string
            if result.lstrip().startswith("<!DOCTYPE") or result.lstrip().startswith("<html"):
                class HTMLResponse:
                    def __init__(self, content: str) -> None:
                        self.content = content
                        self.status_code = 200
                        self.headers = {"content-type": "text/html; charset=utf-8"}
                        self.background = None

                    def body(self) -> bytes:
                        return self.content.encode("utf-8")
                return HTMLResponse(result)
            return JSONResponse({"text": result})

        if isinstance(result, bytes):
            class BytesResponse:
                def __init__(self, content: bytes) -> None:
                    self.content = content
                    self.status_code = 200
                    self.headers = {"content-type": "application/octet-stream"}
                    self.background = None

                def body(self) -> bytes:
                    return self.content
            return BytesResponse(result)

        return JSONResponse({"result": str(result)})

    def _cleanup_callback(self, path: Any, storage: TemporaryStorage) -> Callable[[], None]:
        def _cb() -> None:
            try:
                storage.discard(path)
            except Exception:
                pass
        return _cb

    async def _send_response(self, response: Any, send: Any) -> None:
        is_file = isinstance(response, FileResponse)
        try:
            body = b"" if is_file else response.body() if hasattr(response, "body") else b""
            response_headers = {
                "x-content-type-options": "nosniff",
                "referrer-policy": "no-referrer",
                "x-frame-options": "DENY",
            }
            for key, value in getattr(response, "headers", {}).items():
                response_headers[str(key).lower()] = value
            headers = []
            for key, value in response_headers.items():
                key_text, value_text = str(key), str(value)
                if (
                    not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-z-]+", key_text)
                    or any((ord(char) < 0x20 and char != "\t") or ord(char) == 0x7F for char in value_text)
                ):
                    logger.warning("Skipping invalid HTTP response header: %s", key_text[:80])
                    continue
                try:
                    headers.append((key_text.encode("ascii"), value_text.encode("latin-1")))
                except UnicodeEncodeError:
                    logger.warning("Skipping non-Latin-1 HTTP response header: %s", key_text[:80])
            headers = [(key, value) for key, value in headers if key != b"content-length"]
            content_length = response.path.stat().st_size if is_file else len(body)
            headers.append((b"content-length", str(content_length).encode("latin-1")))
            await send({
                "type": "http.response.start",
                "status": getattr(response, "status_code", 200),
                "headers": headers,
            })
            if is_file:
                with response.path.open("rb") as source:
                    while True:
                        chunk = source.read(64 * 1024)
                        if not chunk:
                            break
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                await send({"type": "http.response.body", "body": body})
        finally:
            bg = getattr(response, "background", None)
            if callable(bg):
                try:
                    bg()
                except Exception:
                    logger.exception("Background cleanup failed")
