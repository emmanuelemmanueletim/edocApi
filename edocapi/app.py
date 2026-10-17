"""eDocAPI ASGI application with built-in routing for document workflows."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import sys
from typing import Any, Callable, Sequence

from edocapi.config import Config
from edocapi.exceptions import EdocAPIError, FileTooLarge
from edocapi.http.multipart import parse_multipart
from edocapi.http.request import Request
from edocapi.responses import FileResponse, JSONResponse, make_error_response
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi")


class Route:
    """Simple route descriptor."""

    __slots__ = ("path", "methods", "endpoint", "name", "pattern")

    def __init__(
        self,
        path: str,
        endpoint: Callable,
        methods: Sequence[str],
        name: str | None = None,
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
    ) -> None:
        self._routes.append(Route(path, endpoint, methods, name=name))

    def get(self, path: str) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["GET"])
            return func
        return decorator

    def post(self, path: str) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["POST"])
            return func
        return decorator

    def put(self, path: str) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["PUT"])
            return func
        return decorator

    def delete(self, path: str) -> Callable:
        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, ["DELETE"])
            return func
        return decorator

    def route(self, path: str, methods: Sequence[str] | None = None) -> Callable:
        methods = methods or ["GET"]

        def decorator(func: Callable) -> Callable:
            self._add_route(path, func, methods)
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
            max_body_size=self.config.max_file_size * self.config.max_files,
        )
        response = await self._handle(request)
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

        request.path_params = path_params
        return await self._dispatch(matched.endpoint, request)

    async def _dispatch(self, endpoint: Callable, request: Request) -> Any:
        from edocapi.document import Document

        uploads: list = []
        try:
            sig = inspect.signature(endpoint)
            kwargs: dict[str, Any] = {}

            # Parse multipart when needed
            form_fields: dict[str, str] = {}
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type.lower() and any(
                p in sig.parameters for p in ("file", "files")
            ):
                body_limit = self.config.max_file_size * self.config.max_files
                body = await request.body(max_size=body_limit)
                uploads, form_fields = await parse_multipart(
                    body,
                    content_type,
                    max_size=self.config.max_file_size,
                    max_files=self.config.max_files,
                    temp_storage=self._temp_storage,
                )
                request._form = form_fields

            for name, param in sig.parameters.items():
                if name == "request":
                    kwargs["request"] = request
                elif name == "file":
                    if not uploads:
                        raise EdocAPIError("No file uploaded.")
                    kwargs["file"] = uploads[0]
                elif name == "files":
                    if not uploads:
                        raise EdocAPIError("No files uploaded.")
                    kwargs["files"] = uploads
                elif name in request.path_params:
                    kwargs[name] = request.path_params[name]
                elif name in form_fields:
                    kwargs[name] = form_fields[name]
                elif name in request.query_params:
                    kwargs[name] = request.query_params[name]
                elif param.default is not inspect.Parameter.empty:
                    continue
                else:
                    continue

            if inspect.iscoroutinefunction(endpoint):
                result = await endpoint(**kwargs)
            else:
                # OCR, conversions, and other synchronous handlers can take
                # seconds or minutes. Keep them off the ASGI event loop so
                # health checks and the dashboard remain responsive meanwhile.
                result = await asyncio.to_thread(endpoint, **kwargs)

            response = self._make_response(result)

        except EdocAPIError as exc:
            status = 413 if isinstance(exc, FileTooLarge) else 400
            logger.warning("eDocAPI error: %s", exc)
            response = make_error_response(exc, status_code=status, debug=self.config.debug)
        except Exception as exc:
            logger.exception("Unhandled error in endpoint")
            response = make_error_response(exc, status_code=500, debug=self.config.debug)

        if uploads:
            previous_background = getattr(response, "background", None)
            upload_cleanup = [self._cleanup_callback(path, self._temp_storage) for path in uploads]

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
            if compression_mode == "pdf":
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
        body = response.body() if hasattr(response, "body") else b""
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
        headers.append((b"content-length", str(len(body)).encode("latin-1")))

        await send({
            "type": "http.response.start",
            "status": getattr(response, "status_code", 200),
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

        # Run background cleanup
        bg = getattr(response, "background", None)
        if callable(bg):
            try:
                bg()
            except Exception:
                logger.exception("Background cleanup failed")
