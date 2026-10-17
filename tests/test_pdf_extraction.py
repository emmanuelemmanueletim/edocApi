"""Regression checks for PDF reading order and block structure."""

from io import BytesIO
import re
from pathlib import Path
import random

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from edocapi import Document
from edocapi.processors.pdf import (
    PDFProcessor,
    _blocks_from_layout,
    _needs_spacing_recovery,
    _restore_stacked_math,
)


def test_spacing_recovery_detects_joined_prose_without_affecting_normal_text():
    assert _needs_spacing_recovery(
        "EngineeringMathematicsII WorkedSolutions "
        "PreparedforShalom UniversityofUyo"
    )
    assert not _needs_spacing_recovery(
        "Engineering Mathematics II — Worked Solutions prepared for Shalom."
    )


def test_stacked_math_is_represented_in_readable_linear_notation():
    assert _restore_stacked_math("𝑣\n2\n(8 mks)") == "𝑣²\n(8 mks)"
    assert _restore_stacked_math("𝑘𝑣2") == "𝑘𝑣²"
    assert _restore_stacked_math("𝑚\n𝑑𝑣\n𝑑𝑡 = 𝑚𝑔") == "𝑚 𝑑𝑣/𝑑𝑡 = 𝑚𝑔"
    assert _restore_stacked_math("Chapter\n2\nOverview") == "Chapter\n2\nOverview"


def test_layout_order_is_preserved_and_heading_depth_is_numbered():
    blocks = _blocks_from_layout([
        "1. Introduction",
        "First paragraph line one",
        "line two continues in source order.",
        "",
        "3.1 Definition and Scope",
        "A body line follows the heading.",
        "2026 so that the reader gets context",
        "any serious evaluation must confront:",
    ], 1)

    headings = [block for block in blocks if block["type"] == "heading"]
    assert [(item["text"], item["level"]) for item in headings] == [
        ("1. Introduction", 2),
        ("3.1 Definition and Scope", 3),
    ]
    assert blocks[1]["text"].startswith("First paragraph line one line two")


def test_bullets_references_and_captions_start_blocks_and_join_wraps():
    blocks = _blocks_from_layout([
        "Context sentence.",
        "",
        "   - First list item",
        "     continuation of the list item",
        "",
        "[2] A reference entry.",
        "    https://example.org/reference",
        "",
        "Table 1. A comparison caption that wraps",
        "          onto the next line.",
    ], 1)

    assert [block["type"] for block in blocks] == [
        "paragraph", "list_item", "reference", "caption",
    ]
    assert blocks[1]["text"] == "- First list item continuation of the list item"
    assert blocks[2]["text"].endswith("https://example.org/reference")
    assert blocks[3]["text"].endswith("onto the next line.")


def test_table_rows_have_stable_column_counts():
    blocks = _blocks_from_layout([
        " Metric       Cloud-only    Edge AI",
        "",
        " Latency      high          low",
        "",
        " Privacy      exposed       local",
    ], 1)

    table = next(block for block in blocks if block["type"] == "table")
    assert [len(row) for row in table["rows"]] == [3, 3, 3]


def test_pdf_compression_compresses_content_after_adding_page_to_writer(tmp_path):
    source = tmp_path / "source.pdf"
    pdf = canvas.Canvas(str(source))
    pdf.drawString(72, 720, "This page contains text that can be compressed.")
    pdf.save()

    compressed = PDFProcessor(source).compress()

    reader = PdfReader(str(compressed))
    assert len(reader.pages) == 1
    assert "This page contains text" in reader.pages[0].extract_text()


def test_pdf_compression_reencodes_images_to_reach_target_size(tmp_path):
    randomizer = random.Random(17)
    image = Image.new("RGB", (400, 400))
    image.putdata([
        (randomizer.randrange(256), randomizer.randrange(256), randomizer.randrange(256))
        for _ in range(400 * 400)
    ])
    image_data = BytesIO()
    image.save(image_data, format="JPEG", quality=95)
    image_data.seek(0)

    source = tmp_path / "image.pdf"
    pdf = canvas.Canvas(str(source))
    pdf.drawString(40, 800, "Text should remain selectable after compression.")
    pdf.drawImage(ImageReader(image_data), 30, 100, width=360, height=360)
    pdf.save()
    target_size = 50 * 1024

    compressed = PDFProcessor(source).compress(target_size=target_size)

    assert source.stat().st_size > 200 * 1024
    assert compressed.stat().st_size <= target_size
    assert "Text should remain selectable" in PdfReader(str(compressed)).pages[0].extract_text()


def test_pdf_compression_rasterizes_vector_pdf_to_reach_target(tmp_path):
    randomizer = random.Random(7)
    source = tmp_path / "vector.pdf"
    pdf = canvas.Canvas(str(source))
    for _ in range(12_000):
        x1, y1, x2, y2 = (
            randomizer.randrange(612),
            randomizer.randrange(792),
            randomizer.randrange(612),
            randomizer.randrange(792),
        )
        pdf.line(x1, y1, x2, y2)
    pdf.save()
    target_size = 25 * 1024

    compressed = PDFProcessor(source).compress(target_size=target_size)

    assert compressed.stat().st_size < source.stat().st_size
    assert compressed.stat().st_size <= target_size
    assert PdfReader(str(compressed)).pages[0].extract_text() == ""


def test_research_report_extraction_regressions():
    path = Path(__file__).parent / "fixtures" / "edge_ai_research_report.pdf"
    result = Document(path).extract_structured_text()
    text = result["text"]
    blocks = result["blocks"]
    source_pages = [page.extract_text(extraction_mode="layout") or "" for page in PdfReader(str(path)).pages]
    source_text = "\n".join(
        page for page in source_pages
        if not re.search(r"^\s*Table of Contents\s*$", page, re.M)
    )

    tokenize = lambda value: re.findall(r"[\w]+(?:[’'-][\w]+)*", value.casefold())
    source_words, extracted_words = tokenize(source_text), tokenize(text)
    source_windows = list(zip(*(source_words[i:] for i in range(5))))
    extracted_windows = set(zip(*(extracted_words[i:] for i in range(5))))
    assert sum(window in extracted_windows for window in source_windows) / len(source_windows) >= 0.95

    headings = [block for block in blocks if block["type"] == "heading"]
    numbered = [block for block in headings if re.match(r"\d", block["text"])]
    assert len(numbered) == 21  # 10 sections plus 11 numbered subsections
    assert all(not re.match(r"[a-z]", block["text"]) for block in headings)
    assert "Table of Contents" not in text
    assert len([block for block in blocks if block["type"] == "reference"]) == 15
    assert all(re.fullmatch(r"\s*\d{1,2}\s*", line) is None for line in text.splitlines())

    tables = [block for block in blocks if block["type"] == "table"]
    assert len(tables) == 2
    assert all(len({len(row) for row in table["rows"]}) == 1 for table in tables)
    assert sum(row[0] == "Metric" for row in tables[0]["rows"]) == 1

    for left, right in [
        ("well supported by", "existing TinyML toolchains"),
        ("model sizes after", "quantisation"),
        ("cloud resources", "retain responsibility"),
        ("No continuous cloud", "connection"),
        ("normal operating conditions", "form the training corpus"),
        ("lifecycle management", "impose continuing"),
    ]:
        assert re.search(re.escape(left) + r"\s+" + re.escape(right), text, re.I)
