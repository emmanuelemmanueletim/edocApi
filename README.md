# eDocAPI

**Pure-Python document processing library & lightweight API framework**  
Version **0.1.1** – completely independent of Starlette, FastAPI, or any external web framework.

[![PyPI](https://img.shields.io/pypi/v/edocapi)](https://pypi.org/project/edocapi/)
[![Python](https://img.shields.io/pypi/pyversions/edocapi)](https://pypi.org/project/edocapi/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

```bash
pip install edocapi
```

---

## What’s new in 0.1.1

- **Zero Starlette dependency** – the framework is built from scratch on pure ASGI.
- **Improved security** – magic-byte validation, strict path sanitization, size limits, content-type checks.
- **ML-powered features** – optional OCR (Tesseract + OpenCV pre-processing) for images and scanned PDFs.
- **Better converters** – smarter image compression, enhanced DOCX/HTML/Markdown → PDF, pure-Python PDF fallback.
- **Cleaner packaging** – installable with a single `pip install edocapi`.
- **Professional CLI** – `edocapi convert|extract|info|ocr|compress`.

See [RELEASE_NOTES_0.1.1.md](RELEASE_NOTES_0.1.1.md) for the full changelog.

### Framework and conversion details in v0.1.1

- DOCX-to-PDF uses ReportLab's paginated layout engine, included in the core dependencies.
- DOCX conversion preserves centered cover titles, heading hierarchy, paragraph order, source table widths, and explicit page breaks.
- Contents pages use readable spacing and indentation for main sections and subsections.
- Tables have visible borders, dark readable text, emphasized first-column labels, and repeating header rows across page breaks.
- The interactive dashboard shows a v0.1.1 feature summary and a single `/health` endpoint card for both GET and POST.
- Dashboard “Try it” responses, errors, and file previews appear in a modal without leaving the dashboard.
- DOCX-to-PDF does not require WeasyPrint's native GTK libraries. The optional `html` extra remains available for HTML/Markdown PDF rendering.

---

## Quick start (library)

```python
from edocapi import Document

# From a file
doc = Document("report.docx")
pdf = doc.to_pdf()
text = doc.extract_text()
info = doc.info()

# From in-memory content
doc = Document.markdown("# Hello\n\nWorld")
pdf = doc.to_pdf()

# OCR (requires: pip install edocapi[ml])
text = Document("scan.png").ocr(lang="eng")

# Merge PDFs
merged = Document.merge(["a.pdf", "b.pdf"])

# Compress
small = Document("large.pdf").compress(target_size=500_000)
```

## Quick start (API server)

```python
# main.py
from edocapi import App, Document

app = App()

@app.post("/convert")
def convert(file):
    return Document(file).to_pdf()

@app.post("/extract")
def extract(file):
    return {"text": Document(file).extract_text()}
```

```bash
pip install edocapi[server]
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 for the interactive developer dashboard.

---

## Supported formats

| Format     | to_pdf | extract_text | OCR | compress | merge |
|------------|--------|--------------|-----|----------|-------|
| PDF        | ✓      | ✓            | ✓*  | ✓        | ✓     |
| DOCX       | ✓      | ✓            | –   | –        | –     |
| HTML       | ✓      | ✓            | –   | –        | –     |
| Markdown   | ✓      | ✓            | –   | –        | –     |
| TXT        | ✓      | ✓            | –   | –        | –     |
| JPEG/PNG/WebP | ✓   | ✓*           | ✓*  | ✓        | –     |

\* Requires optional extras: `pip install edocapi[ml]` (and `edocapi[pdf-images]` for PDF page rendering).

---

## Optional extras

```bash
pip install edocapi[html]        # high-quality HTML/Markdown → PDF (WeasyPrint)
pip install edocapi[pdf-images]  # PDF → images (pdf2image)
pip install edocapi[ml]          # OCR + OpenCV pre-processing
pip install edocapi[all]         # everything
pip install edocapi[server]      # uvicorn for running the App
```

DOCX-to-PDF uses ReportLab's paginated layout engine, included in the core
dependencies. It preserves Word paragraph styling and renders tables with visible
borders without requiring native GTK libraries.

---

## Security highlights

- Filenames are sanitized (basename only, dangerous characters stripped).
- Magic-byte verification prevents extension spoofing.
- Configurable maximum file size and file count.
- Streaming request reads enforce the configured request-size budget; multipart fields and uploads have separate count and size limits.
- Uploads use generated, collision-resistant temporary names, and temporary cleanup is confined to registered paths under the storage root.
- Dashboard route metadata is HTML-escaped, route templates are validated, response filenames are encoded safely, and responses include baseline browser security headers.
- Temporary files are isolated and cleaned up automatically.
- No execution of document content; pure data processing.

---

## CLI

```bash
edocapi --version
edocapi convert report.docx -o report.pdf
edocapi extract report.pdf
edocapi info image.png
edocapi ocr scan.png --lang eng
edocapi compress large.pdf --target 500KB
```

---

## License

MIT © EMMANUEL EMMANUEL ETIM
