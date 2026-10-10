"""
eDocAPI Web Application
Landing page + dashboard for document processing.
Powered by the eDocAPI framework.
"""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from edocapi import App, Document
from edocapi.exceptions import EdocAPIError
from edocapi import __version__

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = App(debug=True, max_file_size="25MB")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _mount_static() -> None:
    """Attach /static once the Starlette app exists."""
    starlette = app.asgi
    # Avoid double-mount
    for route in starlette.routes:
        if getattr(route, "path", None) == "/static":
            return
    starlette.routes.append(
        Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static")
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
async def landing(request: Request):
    _mount_static()
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"version": __version__},
    )


@app.get("/dashboard")
async def dashboard(request: Request):
    _mount_static()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "version": __version__,
            "supported": Document.supported_types(),
        },
    )


@app.get("/docs-ui")
async def docs_page(request: Request):
    _mount_static()
    return templates.TemplateResponse(
        request,
        "docs.html",
        {"version": __version__},
    )


# ---------------------------------------------------------------------------
# API — health / meta
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "framework": "eDocAPI",
        "version": __version__,
        "supported_types": Document.supported_types(),
    }


@app.get("/api/formats")
def formats():
    return {
        "formats": Document.supported_types(),
        "operations": [
            {"id": "convert", "label": "Convert to PDF"},
            {"id": "extract", "label": "Extract text"},
            {"id": "compress", "label": "Compress PDF and images"},
            {"id": "merge", "label": "Merge PDFs"},
            {"id": "split", "label": "Split / extract pages"},
            {"id": "info", "label": "Document info"},
            {"id": "html2pdf", "label": "HTML to PDF"},
            {"id": "md2pdf", "label": "Markdown to PDF"},
        ],
    }


# ---------------------------------------------------------------------------
# API — document operations (using eDocAPI Document)
# ---------------------------------------------------------------------------

@app.post("/api/convert")
def api_convert(file):
    return Document(file).to_pdf()


@app.post("/api/extract")
def api_extract(file):
    doc = Document(file)
    text = doc.extract_text()
    return {
        "success": True,
        "filename": doc.name,
        "type": doc.type,
        "text": text,
        "characters": len(text),
    }


@app.post("/api/compress")
def api_compress(file, target_size_value: str = "", target_unit: str = "MB"):
    doc = Document(file)
    if doc.type not in {"pdf", "jpeg", "jpg", "png", "webp"}:
        raise EdocAPIError(
            "Compression supports PDF, JPG, JPEG, PNG, and WebP files only."
        )
    target_bytes = None
    if target_size_value:
        try:
            multiplier = {"KB": 1024, "MB": 1024 * 1024}[target_unit.upper()]
            target_bytes = int(float(target_size_value) * multiplier)
        except KeyError as exc:
            raise EdocAPIError("Target unit must be KB or MB.") from exc
        except ValueError as exc:
            raise EdocAPIError("Target size must be a valid number.") from exc
        if target_bytes <= 0:
            raise EdocAPIError("Target size must be greater than zero.")
    return doc.compress(level="medium", target_size=target_bytes)


@app.post("/api/merge")
def api_merge(files):
    docs = [Document(f) for f in files]
    for d in docs:
        if d.type != "pdf":
            raise EdocAPIError(f"Merge requires PDF files. Got: {d.name} ({d.type})")
    return Document.merge([d.path for d in docs])


@app.post("/api/split-info")
def api_split_info(file):
    doc = Document(file)
    if doc.type != "pdf":
        raise EdocAPIError("Only PDF files can be split.")
    info = doc.info()
    return {
        "success": True,
        "filename": doc.name,
        "pages": info.get("pages", 0),
        "size": doc.size,
    }


@app.post("/api/info")
def api_info(file):
    doc = Document(file)
    data = doc.info()
    data["success"] = True
    return data


@app.post("/api/extract-pages")
def api_extract_pages(file, request: Request):
    start = int(request.query_params.get("start", "1"))
    end_raw = request.query_params.get("end")
    end = int(end_raw) if end_raw else None
    doc = Document(file)
    if doc.type != "pdf":
        raise EdocAPIError("Page extraction only works with PDF files.")
    return doc.extract_pages(start, end)


@app.post("/api/html-to-pdf")
async def api_html_to_pdf(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise EdocAPIError("Send JSON with an 'html' field.")
    html = (payload or {}).get("html") or ""
    if not str(html).strip():
        raise EdocAPIError("HTML content is empty.")
    return Document.html(str(html)).to_pdf()


@app.post("/api/markdown-to-pdf")
async def api_markdown_to_pdf(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise EdocAPIError("Send JSON with a 'markdown' field.")
    md = (payload or {}).get("markdown") or ""
    if not str(md).strip():
        raise EdocAPIError("Markdown content is empty.")
    return Document.markdown(str(md)).to_pdf()


# Eagerly create ASGI app and mount static so first request is fast
_mount_static()
