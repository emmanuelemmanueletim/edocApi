"""Core tests for eDocAPI 0.1.1."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from edocapi import Document, __version__
from edocapi.exceptions import SecurityError, UnsupportedFileType, InvalidDocument
from edocapi.storage.temporary import safe_filename, TemporaryStorage
from edocapi.validation.files import detect_type_from_bytes, validate_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_version():
    assert __version__ == "0.1.1"


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("normal.pdf") == "normal.pdf"
    assert ".." not in safe_filename("../evil.txt")
    assert safe_filename("") == "unnamed"


def test_detect_pdf_magic():
    data = b"%PDF-1.4\n..."
    assert detect_type_from_bytes(data) == "pdf"


def test_detect_png_magic():
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert detect_type_from_bytes(data) == "png"


def test_document_from_text():
    doc = Document.text("Hello eDocAPI")
    assert doc.type == "txt"
    assert "Hello" in doc.extract_text()


def test_document_to_pdf_from_text():
    doc = Document.text("Hello world\nSecond line")
    pdf = doc.to_pdf()
    assert pdf.type == "pdf"
    assert pdf.size > 0
    assert pdf.path.suffix == ".pdf"


def test_document_markdown():
    doc = Document.markdown("# Title\n\nSome **bold** text.")
    assert doc.type == "markdown"
    html = doc.to_html()
    assert "<h1>" in html or "Title" in html


def test_supported_types():
    types = Document.supported_types()
    assert "pdf" in types
    assert "docx" in types
    assert "txt" in types


def test_info():
    doc = Document.text("sample")
    info = doc.info()
    assert "filename" in info
    assert "size" in info


@pytest.mark.skipif(not (FIXTURES / "sample.txt").exists(), reason="fixture missing")
def test_fixture_txt():
    path = FIXTURES / "sample.txt"
    doc = Document(path)
    assert doc.type == "txt"
    text = doc.extract_text()
    assert len(text) >= 0


def test_security_path_traversal():
    # Creating Document with a non-existent traversal path should fail cleanly
    with pytest.raises((InvalidDocument, FileNotFoundError, OSError)):
        Document("/tmp/../../../etc/passwd")
