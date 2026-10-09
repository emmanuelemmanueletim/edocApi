"""Core tests for eDocAPI v0.0.1."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from edocapi import App, Document, __version__
from edocapi.exceptions import UnsupportedFileType, FileTooLarge

FIXTURES = Path(__file__).parent / "fixtures"


def test_version():
    assert __version__ == "0.1.0"


def test_supported_types():
    types = Document.supported_types()
    assert "pdf" in types
    assert "docx" in types
    assert "html" in types
    assert "markdown" in types
    assert "png" in types


def test_document_from_pdf():
    doc = Document(FIXTURES / "sample.pdf")
    assert doc.type == "pdf"
    assert doc.extension == ".pdf"
    assert doc.size > 0
    info = doc.info()
    assert info["pages"] == 1
    assert "filename" in info


def test_document_from_docx():
    doc = Document(FIXTURES / "sample.docx")
    assert doc.type == "docx"
    text = doc.extract_text()
    assert "Hello eDocAPI" in text
    html = doc.to_html()
    assert "<h1>" in html or "Hello" in html


def test_html_to_pdf():
    pytest.importorskip("weasyprint", reason="HTML-to-PDF requires the optional html extra")
    doc = Document.html("<html><body><h1>Invoice</h1><p>Total: 50000</p></body></html>")
    pdf = doc.to_pdf()
    assert pdf.type == "pdf"
    assert pdf.size > 0


def test_markdown_to_pdf():
    pytest.importorskip("weasyprint", reason="Markdown-to-PDF requires the optional html extra")
    doc = Document.markdown("# Hello World\n\nThis is a test.")
    pdf = doc.to_pdf()
    assert pdf.type == "pdf"


def test_image_to_pdf():
    doc = Document(FIXTURES / "sample.png")
    pdf = doc.to_pdf()
    assert pdf.type == "pdf"
    assert pdf.size > 0


def test_pdf_text_extraction():
    doc = Document(FIXTURES / "sample.pdf")
    text = doc.extract_text()
    assert isinstance(text, str)


def test_pdf_compress():
    doc = Document(FIXTURES / "sample.pdf")
    compressed = doc.compress(level="medium")
    assert compressed.type == "pdf"
    assert compressed.size > 0


def test_pdf_split():
    doc = Document(FIXTURES / "sample.pdf")
    pages = doc.split()
    assert len(pages) == 1
    assert pages[0].type == "pdf"


def test_pdf_extract_pages():
    doc = Document(FIXTURES / "sample.pdf")
    extracted = doc.extract_pages(1, 1)
    assert extracted.type == "pdf"


def test_merge():
    f1 = FIXTURES / "sample.pdf"
    f2 = FIXTURES / "sample.pdf"
    merged = Document.merge([f1, f2])
    assert merged.type == "pdf"
    assert merged.info()["pages"] == 2


@pytest.mark.asyncio
async def test_app_home():
    app = App(debug=True)

    @app.get("/")
    def home():
        return {"message": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.json()["message"] == "ok"


@pytest.mark.asyncio
async def test_app_convert():
    app = App(debug=True)

    @app.post("/convert")
    def convert(file):
        return Document(file).to_pdf()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(FIXTURES / "sample.png", "rb") as f:
            resp = await client.post(
                "/convert",
                files={"file": ("sample.png", f, "image/png")},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert len(resp.content) > 0


def test_file_too_large():
    app = App(max_file_size="1B")  # ridiculously small
    # Just verify config parses
    assert app.config.max_file_size == 1
