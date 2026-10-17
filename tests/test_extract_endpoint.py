from pathlib import Path

import httpx
import pytest

from edocapi import App, Document
from edocapi.config import MAX_FILE_SIZE_BYTES
from edocapi.responses import JSONResponse
from edocapi.exceptions import FileTooLarge, InvalidDocument, ProcessingError, SecurityError, ValidationError
from edocapi.http.multipart import _parse_pure
from edocapi.storage.temporary import TemporaryStorage
from edocapi.http.multipart import parse_multipart
from edocapi.responses import FileResponse
from edocapi.processors.safe_fetch import blocked_url_fetcher
from edocapi.processors.html import HTMLProcessor
from edocapi.processors.markdown import MarkdownProcessor


def test_app_upload_limit_defaults_to_50mb_and_accepts_smaller_values():
    assert App(dashboard=False).config.max_file_size == MAX_FILE_SIZE_BYTES
    assert App(max_file_size="10MB", dashboard=False).config.max_file_size == 10 * 1024 * 1024
    with pytest.raises(ValueError, match="cannot exceed"):
        App(max_file_size="51MB", dashboard=False)


def test_json_response_preserves_unicode_for_all_clients():
    response = JSONResponse({"text": "𝑣 = √𝑥 — Ω"})
    body = response.body()
    assert body.isascii()
    assert body.decode("ascii") == '{"text": "\\ud835\\udc63 = \\u221a\\ud835\\udc65 \\u2014 \\u03a9"}'


@pytest.mark.asyncio
async def test_extract_endpoint_returns_text_and_cleans_uploaded_file(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/extract")
    def extract(file):
        return {"text": Document(file).extract_text()}

    fixture = Path(__file__).parent / "fixtures" / "edge_ai_research_report.pdf"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/extract",
            files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["text"].startswith("# ARTIFICIAL INTELLIGENCE AT THE EDGE:")
    assert not app._temp_storage._files
    assert not app._temp_storage._registered
    app._temp_storage.cleanup()


def test_document_read_does_not_create_a_temporary_root(tmp_path):
    path = tmp_path / "readme.txt"
    path.write_text("hello", encoding="utf-8")

    document = Document(path)
    assert document.extract_text() == "hello"
    assert document._temp._root is None
    assert not document._temp._registered


def test_owned_temporary_root_is_removed_after_last_file_is_discarded():
    storage = TemporaryStorage()
    path = storage.create_file(suffix=".txt")
    root = storage.root

    assert root.is_dir()
    assert storage._registered
    storage.discard(path)
    assert not root.exists()
    assert storage._root is None
    assert not storage._registered


def test_multipart_parser_cleans_partial_uploads_on_rejection(tmp_path):
    storage = TemporaryStorage(tmp_path)
    boundary = "boundary"
    body = (
        b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"one.pdf\"\r\n"
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n"
        b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"two.pdf\"\r\n"
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n--boundary--\r\n"
    )

    with pytest.raises(ValidationError):
        _parse_pure(body, f"multipart/form-data; boundary={boundary}",
                    max_size=1024, max_files=1, temp_storage=storage)

    assert not storage._files
    storage.cleanup()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1:9/internal"])
def test_pdf_resource_fetcher_blocks_local_and_network_urls(url):
    with pytest.raises(ValueError, match="resources are blocked"):
        blocked_url_fetcher(url)


@pytest.mark.parametrize(
    "processor_type,content",
    [(HTMLProcessor, '<img src="file:///etc/passwd">'),
     (MarkdownProcessor, "![network](http://127.0.0.1:9/internal)")],
)
def test_html_and_markdown_pdf_use_restrictive_fetcher(tmp_path, monkeypatch, processor_type, content):
    import sys
    from types import SimpleNamespace

    seen = {}

    class FakeHTML:
        def __init__(self, *args, **kwargs):
            seen["fetcher"] = kwargs.get("url_fetcher")

        def write_pdf(self, path):
            Path(path).write_bytes(b"%PDF-test")

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=FakeHTML))
    suffix = ".html" if processor_type is HTMLProcessor else ".md"
    path = tmp_path / f"input{suffix}"
    path.write_text(content, encoding="utf-8")
    result = processor_type(path).to_pdf()
    assert result.read_bytes().startswith(b"%PDF")
    assert seen["fetcher"] is blocked_url_fetcher


@pytest.mark.asyncio
async def test_streaming_multipart_parser_and_total_limit(tmp_path):
    storage = TemporaryStorage(tmp_path)
    body = (
        b'--b\r\nContent-Disposition: form-data; name="title"\r\n\r\nhello\r\n'
        b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\nabc123\r\n--b--\r\n'
    )

    async def chunks():
        for i in range(0, len(body), 3):
            yield body[i:i + 3]

    paths, fields = await parse_multipart(
        chunks(), "multipart/form-data; boundary=b", max_size=32, max_files=2,
        temp_storage=storage, max_request_size=len(body),
    )
    assert fields == {"title": "hello"}
    assert paths[0].read_bytes() == b"abc123"

    async def too_large():
        yield body

    with pytest.raises(FileTooLarge, match="configured limit"):
        await parse_multipart(
            too_large(), "multipart/form-data; boundary=b", max_size=32, max_files=2,
            temp_storage=storage, max_request_size=len(body) - 1,
        )
    storage.cleanup()


@pytest.mark.asyncio
async def test_file_response_streams_chunks_and_cleans_up_on_disconnect(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)
    path = app._temp_storage.create_file(suffix=".bin", content=b"x" * 200_000)
    response = FileResponse(path, background=app._cleanup_callback(path, app._temp_storage))
    messages = []

    async def disconnecting_send(message):
        messages.append(message)
        if message.get("type") == "http.response.body" and message.get("body"):
            raise RuntimeError("client disconnected")

    with pytest.raises(RuntimeError, match="disconnected"):
        await app._send_response(response, disconnecting_send)
    assert messages[0]["type"] == "http.response.start"
    assert len(messages[1]["body"]) < 200_000
    assert not path.exists()
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_direct_uploaded_file_response_is_streamed_before_cleanup(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/echo")
    def echo(file):
        return Path(file)

    fixture = Path(__file__).parent / "fixtures" / "sample.txt"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/echo", files={"file": (fixture.name, fixture.read_bytes())})
    assert response.status_code == 200
    assert response.content == fixture.read_bytes()
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


def test_document_merge_rejects_non_pdf(tmp_path):
    source = tmp_path / "wrong.txt"
    source.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(InvalidDocument):
        Document.merge([source])


def test_config_extensions_and_request_limit():
    app = App(dashboard=False, max_request_size="2MB", allowed_extensions={".pdf"})
    assert app.config.max_request_size == 2 * 1024 * 1024
    assert app.config.allowed_extensions == {".pdf"}


@pytest.mark.asyncio
async def test_app_applies_upload_extension_allowlist(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False, allowed_extensions={".pdf"})

    @app.post("/upload")
    def upload(file):
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/upload", files={"file": ("bad.txt", b"content")})
    assert response.status_code == 415
    assert "not allowed" in response.json()["message"]
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_missing_upload_returns_predictable_400_without_handler_call(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)
    called = False

    @app.post("/convert")
    def convert(file):
        nonlocal called
        called = True
        return Document(file).to_pdf()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/convert", data={})
    assert response.status_code == 400
    assert response.json()["error"] == "MissingUpload"
    assert "No file uploaded" in response.json()["message"]
    assert not called
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_missing_required_form_parameter_returns_400(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/resize")
    def resize(file, width: int):
        return {"width": width}

    fixture = Path(__file__).parent / "fixtures" / "sample.png"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/resize", files={"file": (fixture.name, fixture.read_bytes())})
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"
    assert "width" in response.json()["message"]
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_corrupt_upload_returns_client_error_and_cleans_temp_file(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/convert")
    def convert(file):
        return Document(file).to_pdf()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/convert", files={"file": ("broken.pdf", b"not really a pdf")})
    assert response.status_code == 415
    assert response.json()["error"] == "SecurityError"
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_upload_cleanup_runs_when_existing_background_callback_raises(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/custom")
    def custom(file):
        response = JSONResponse({"ok": True})

        def fail_background():
            raise RuntimeError("custom callback failed")

        response.background = fail_background
        return response

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/custom", files={"file": ("note.txt", b"hello")})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_encrypted_pdf_upload_returns_predictable_400(tmp_path):
    from pypdf import PdfWriter

    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with encrypted.open("wb") as output:
        writer.write(output)
    app = App(temp_dir=str(tmp_path / "uploads"), dashboard=False)

    @app.post("/convert")
    def convert(file):
        return Document(file).to_pdf()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/convert", files={"file": (encrypted.name, encrypted.read_bytes())})
    assert response.status_code == 400
    assert response.json()["error"] == "InvalidDocument"
    assert "Encrypted PDFs are not supported" in response.json()["message"]
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_magic_mismatch_upload_returns_415(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/convert")
    def convert(file):
        return Document(file).to_pdf()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/convert", files={"file": ("wrong.pdf", b"valid utf8 text")})
    assert response.status_code == 415
    assert response.json()["error"] == "SecurityError"
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_request_size_limit_rejects_before_multipart_parsing(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False, max_request_size=64)

    @app.post("/upload")
    def upload(file):
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", files={"file": ("small.txt", b"data")})
    assert response.status_code == 413
    assert response.json()["error"] == "FileTooLarge"
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_endpoint_internal_errors_are_generic_and_clean_upload(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False, debug=True)

    @app.post("/fail")
    def fail(file):
        raise RuntimeError("private path: C:\\secret\\document.pdf")

    fixture = Path(__file__).parent / "fixtures" / "sample.txt"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/fail", files={"file": (fixture.name, fixture.read_bytes())})
    assert response.status_code == 500
    assert response.json()["message"] == "An internal error occurred."
    assert "secret" not in response.text
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_converter_unexpected_error_returns_generic_500(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False, debug=True)

    @app.post("/convert")
    def convert(file):
        raise RuntimeError("renderer exploded at C:\\private\\file.pdf")

    fixture = Path(__file__).parent / "fixtures" / "sample.txt"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/convert", files={"file": (fixture.name, fixture.read_bytes())})
    assert response.status_code == 500
    assert response.json() == {"error": "RuntimeError", "message": "An internal error occurred."}
    assert "private" not in response.text
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


def test_empty_document_operations_raise_domain_error():
    empty = Document()
    with pytest.raises(InvalidDocument, match="empty"):
        empty.to_pdf()
    with pytest.raises(InvalidDocument, match="empty"):
        empty.to_text()


def test_binary_content_cannot_claim_text_extension(tmp_path):
    spoofed = tmp_path / "spoofed.txt"
    spoofed.write_bytes(b"\x00\x01\xff\x80binary")
    with pytest.raises(SecurityError):
        Document(spoofed)


def test_image_with_excessive_pixel_dimensions_is_rejected(tmp_path, monkeypatch):
    from PIL import Image
    from edocapi.processors.image import ImageProcessor

    path = tmp_path / "huge.png"
    path.write_bytes(b"not decoded because header dimensions are rejected")

    class HeaderOnlyImage:
        width = 200_000
        height = 200_000

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(Image, "open", lambda *args, **kwargs: HeaderOnlyImage())
    with pytest.raises(InvalidDocument, match="pixel processing limit"):
        ImageProcessor(path)


def test_pdf_magic_mismatch_is_rejected(tmp_path):
    spoofed = tmp_path / "spoofed.pdf"
    spoofed.write_text("plain text pretending to be a PDF", encoding="utf-8")
    with pytest.raises(SecurityError):
        Document(spoofed)


def test_encrypted_pdf_is_rejected_predictably(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(InvalidDocument, match="Encrypted PDFs are not supported"):
        Document(path).to_pdf()


def test_unexpected_error_response_never_discloses_exception_details():
    from edocapi.responses import make_error_response

    response = make_error_response(RuntimeError("C:\\private\\secret.pdf failed"), status_code=500, debug=True)
    assert response.status_code == 500
    assert "secret.pdf" not in response.body().decode("ascii")
    assert "traceback" not in response.body().decode("ascii")


def test_file_response_uses_non_executable_mime_for_html(tmp_path):
    path = tmp_path / "untrusted.html"
    path.write_text("<script>alert(1)</script>", encoding="utf-8")
    response = FileResponse(path)
    assert response.headers["content-type"] == "application/octet-stream"
    explicit = FileResponse(path, media_type="text/html; charset=utf-8")
    assert explicit.headers["content-type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_ocr_route_is_disabled_by_default_and_uses_configured_language(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/ocr")
    def ocr(file, lang="eng", engine="tesseract"):
        return {"lang": lang, "engine": engine}

    fixture = Path(__file__).parent / "fixtures" / "sample.png"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        disabled = await client.post("/ocr", files={"file": (fixture.name, fixture.read_bytes())})
    assert disabled.status_code == 400
    assert "OCR is disabled" in disabled.json()["message"]
    assert not app._temp_storage._files
    app._temp_storage.cleanup()

    enabled_app = App(temp_dir=str(tmp_path / "enabled"), dashboard=False, enable_ocr=True, ocr_lang="fra")
    @enabled_app.post("/ocr")
    def configured_ocr(file, lang="eng", engine="tesseract"):
        return {"lang": lang, "engine": engine}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=enabled_app), base_url="http://test") as client:
        enabled = await client.post("/ocr", files={"file": (fixture.name, fixture.read_bytes())})
    assert enabled.status_code == 200
    assert enabled.json()["lang"] == "fra"
    enabled_app._temp_storage.cleanup()


def test_example_application_enables_ocr_route():
    # ``uvicorn main:app`` is the documented runnable example and registers
    # /ocr, so its config must enable the route's explicit safety gate.
    import main

    assert main.app.config.enable_ocr is True


def test_html_renderer_missing_uses_basic_pdf_fallback(tmp_path, monkeypatch):
    import builtins
    from edocapi.processors.html import HTMLProcessor

    path = tmp_path / "plain.html"
    path.write_text("<html><body><p>Hello</p></body></html>", encoding="utf-8")
    original_import = builtins.__import__

    def import_without_weasyprint(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_weasyprint)
    output = HTMLProcessor(path).to_pdf()
    assert output.is_file() and output.stat().st_size > 0


def test_unsupported_operation_raises_framework_error():
    with pytest.raises(ProcessingError, match="not supported"):
        Document.text("plain text").extract_structured_text()


def test_html_renderer_failure_removes_partial_output(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from edocapi.exceptions import ConversionError

    storage = TemporaryStorage(tmp_path)

    class BrokenHTML:
        def __init__(self, *args, **kwargs):
            pass

        def write_pdf(self, target):
            Path(target).write_bytes(b"partial")
            raise RuntimeError("private renderer details")

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=BrokenHTML))
    document = Document(
        "<html><body><p>safe</p></body></html>".encode(),
        filename="safe.html", doc_type="html",
        temp_storage=storage,
    )
    with pytest.raises(ConversionError):
        document.to_pdf()
    assert storage._files == {document.path}
    assert not list(tmp_path.glob("html_*.pdf"))
    storage.cleanup()


def test_encrypted_pdf_merge_is_rejected(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(InvalidDocument, match="Encrypted PDFs are not supported"):
        Document.merge([path])


@pytest.mark.asyncio
async def test_streaming_multipart_truncation_cleans_active_upload(tmp_path):
    storage = TemporaryStorage(tmp_path)
    content = (
        b'--b\r\nContent-Disposition: form-data; name="file"; filename="large.txt"\r\n\r\n'
        + b"x" * 50
    )

    async def chunks():
        yield content[:100]
        yield content[100:]

    with pytest.raises(ValidationError, match="Incomplete"):
        await parse_multipart(
            chunks(), "multipart/form-data; boundary=b", max_size=100, max_files=1,
            temp_storage=storage, max_request_size=1024,
        )
    assert not storage._files
    storage.cleanup()


@pytest.mark.asyncio
async def test_multipart_content_length_rejected_before_reading(tmp_path):
    storage = TemporaryStorage(tmp_path)

    async def unused_stream():
        raise AssertionError("oversized body should be rejected before reading")
        yield b""

    with pytest.raises(FileTooLarge):
        await parse_multipart(
            unused_stream(), "multipart/form-data; boundary=b", max_size=20,
            max_files=1, temp_storage=storage, max_request_size=100,
            content_length=101,
        )
    assert not storage._files
    storage.cleanup()


@pytest.mark.asyncio
async def test_request_body_enforces_total_limit_without_content_length():
    from edocapi.http.request import Request

    messages = iter([
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678", "more_body": False},
    ])

    async def receive():
        return next(messages)

    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": []},
        receive,
        max_body_size=7,
    )
    with pytest.raises(FileTooLarge):
        await request.body()
