"""Example developer application showing eDocAPI's built-in API explorer.

Run with:
    pip install edocapi[server]
    uvicorn main:app --reload
"""

from edocapi import App, Document, __version__

app = App()


@app.post("/convert")
def convert(file):
    """Convert an uploaded supported document to PDF."""
    return Document(file).to_pdf()


@app.post("/compress")
def compress(file, target_size_value: str = "", target_unit: str = "MB"):
    """Compress a PDF or JPG/JPEG/PNG/WebP image, optionally setting a maximum size."""
    target_bytes = None
    if target_size_value:
        units = {"KB": 1024, "MB": 1024 * 1024}
        unit = target_unit.upper()
        if unit not in units:
            from edocapi.exceptions import ProcessingError
            raise ProcessingError("Target unit must be KB or MB.")
        try:
            target_bytes = int(float(target_size_value) * units[unit])
        except ValueError as exc:
            from edocapi.exceptions import ProcessingError
            raise ProcessingError("Target size must be a number.") from exc
    document = Document(file)
    if document.type not in {"pdf", "jpeg", "jpg", "png", "webp"}:
        from edocapi.exceptions import ProcessingError
        raise ProcessingError(
            "Compression supports PDF, JPG, JPEG, PNG, and WebP files only."
        )
    return document.compress(target_size=target_bytes)


@app.post("/extract")
def extract(file):
    """Extract text from an uploaded document."""
    return {"text": Document(file).extract_text()}


@app.post("/ocr")
def ocr(file, lang: str = "eng", engine: str = "tesseract"):
    """Extract PDF text directly; OCR image and scanned PDF pages. English is the default.

    Tesseract requires edocapi[ml] when an uploaded page needs OCR. Set
    engine=paddle for advanced document layout, table, formula, and seal
    recognition; chart parsing can be enabled with
    EDOCAPI_PADDLE_CHART_RECOGNITION=1. Paddle requires edocapi[structured-ocr]
    on Python 3.13 or earlier for pages that need OCR.
    """
    return {"text": Document(file).ocr(lang=lang, engine=engine)}


@app.post("/info")
def info(file):
    """Read metadata from an uploaded document."""
    return Document(file).info()


@app.post("/merge")
def merge(files):
    """Merge uploaded PDF files into one PDF."""
    return Document.merge(files)
