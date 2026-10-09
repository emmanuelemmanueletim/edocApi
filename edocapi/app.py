"""eDocAPI application object built on Starlette."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Sequence

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.exceptions import ExceptionMiddleware

from edocapi.config import Config
from edocapi.exceptions import EdocAPIError
from edocapi.responses import JSONResponse, make_error_response
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi")


class App:
    """Main eDocAPI application.

    Example::

        from edocapi import App, Document

        app = App()

        @app.post("/convert")
        def convert(file):
            return Document(file).to_pdf()
    """

    def __init__(
        self,
        debug: bool = False,
        max_file_size: str | int = "10MB",
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
        self._dashboard_enabled = bool(kwargs.get("dashboard", True))
        self._dashboard_endpoint: Callable | None = None
        self._temp_storage = TemporaryStorage(self.config.temp_dir)
        self._starlette: Starlette | None = None

        # Configure logging
        level = logging.DEBUG if self.config.debug else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(levelname)-5s  %(name)s  %(message)s",
        )

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def _add_route(
        self,
        path: str,
        endpoint: Callable,
        methods: Sequence[str],
    ) -> None:
        """Register a route, wrapping the endpoint to inject request context."""

        async def wrapper(request: Request) -> Response:
            return await self._dispatch(endpoint, request)

        self._routes.append(Route(path, endpoint=wrapper, methods=list(methods)))

    def _dashboard_response(self) -> Response:
        """Build the interactive developer dashboard from this app's routes."""
        from edocapi.document import Document
        from edocapi.dashboard import render_dashboard

        routes = [
            {"path": route.path, "methods": sorted(route.methods or []), "name": getattr(route.endpoint, "__name__", "endpoint")}
            for route in self._routes
        ]
        return Response(
            render_dashboard(routes, Document.supported_types(), self.config.max_file_size),
            media_type="text/html",
        )

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
    # Request dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, endpoint: Callable, request: Request) -> Response:
        """Call the user endpoint, injecting file uploads and handling results."""
        from edocapi.document import Document
        from edocapi.files import extract_uploads

        try:
            # Prepare keyword arguments for the endpoint
            sig = inspect.signature(endpoint)
            kwargs: dict[str, Any] = {}

            # Inject uploads when the parameter is named 'file' or 'files'
            uploads = None
            if any(p in sig.parameters for p in ("file", "files")):
                uploads = await extract_uploads(
                    request,
                    max_size=self.config.max_file_size,
                    max_files=self.config.max_files,
                    temp_storage=self._temp_storage,
                )

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
                elif param.default is not inspect.Parameter.empty:
                    continue
                else:
                    # Try query params as fallback
                    if name in request.query_params:
                        kwargs[name] = request.query_params[name]

            # Call the endpoint (sync or async)
            if inspect.iscoroutinefunction(endpoint):
                result = await endpoint(**kwargs)
            else:
                result = endpoint(**kwargs)

            return self._make_response(result)

        except EdocAPIError as exc:
            status = 400
            if exc.__class__.__name__ == "FileTooLarge":
                status = 413
            logger.warning("eDocAPI error: %s", exc)
            return make_error_response(exc, status_code=status, debug=self.config.debug)
        except Exception as exc:
            logger.exception("Unhandled error in endpoint")
            return make_error_response(
                exc, status_code=500, debug=self.config.debug
            )

    def _make_response(self, result: Any) -> Response:
        """Convert an endpoint return value into a Starlette Response."""
        from edocapi.document import Document
        from edocapi.responses import FileResponse, JSONResponse
        from pathlib import Path

        if result is None:
            return JSONResponse({"success": True})

        if isinstance(result, Response):
            return result

        if isinstance(result, Document):
            # Document returned directly  treat as file response
            path = result.path
            return FileResponse(
                path,
                filename=path.name,
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
            return JSONResponse({"text": result})

        if isinstance(result, bytes):
            return Response(content=result, media_type="application/octet-stream")

        # Fallback
        return JSONResponse({"result": str(result)})

    @staticmethod
    def _cleanup_callback(path: Path, storage: TemporaryStorage):
        """Clean up managed output files after Starlette finishes streaming."""
        from starlette.background import BackgroundTask

        return BackgroundTask(storage.discard, path) if path in storage._files else None

    # ------------------------------------------------------------------
    # ASGI interface
    # ------------------------------------------------------------------

    @property
    def asgi(self) -> Starlette:
        """Return the underlying Starlette ASGI application."""
        if self._starlette is None:
            routes = list(self._routes)
            if self._dashboard_enabled and not any(r.path == "/" and "GET" in (r.methods or []) for r in routes):
                async def dashboard_endpoint(request: Request) -> Response:
                    return self._dashboard_response()

                self._dashboard_endpoint = dashboard_endpoint
                routes.insert(0, Route("/", endpoint=dashboard_endpoint, methods=["GET"]))
            self._starlette = Starlette(
                debug=self.config.debug,
                routes=routes,
                exception_handlers={
                    Exception: self._global_exception_handler,
                },
            )
        return self._starlette

    async def _global_exception_handler(
        self, request: Request, exc: Exception
    ) -> Response:
        logger.exception("Unhandled ASGI exception")
        return make_error_response(exc, status_code=500, debug=self.config.debug)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI callable  delegates to the Starlette app."""
        await self.asgi(scope, receive, send)

    def __repr__(self) -> str:
        return f"<eDocAPI App debug={self.config.debug}>"
