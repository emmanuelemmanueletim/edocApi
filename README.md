# eDocAPI

**A Python toolkit for practical document workflows.**

Version **0.1.3** refreshes the release metadata and PyPI project description.

[![PyPI](https://img.shields.io/pypi/v/edocapi?cacheSeconds=300)](https://pypi.org/project/edocapi/)
[![Python](https://img.shields.io/pypi/pyversions/edocapi)](https://pypi.org/project/edocapi/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

```bash
pip install edocapi
```

---

## Highlights in 0.1.3

- **One document toolkit** – convert, extract, recognize, compress, and merge documents through a consistent Python interface.
- **Structured recognition** – optional PaddleOCR adds page layout, table, and formula recognition.
- **Careful file handling** – uploads are validated, size-limited, and stored with controlled temporary-file cleanup.
- **Readable document output** – DOCX-to-PDF preserves headings, page breaks, table widths, and repeating table headers.
- **Tools for developers** – use the Python library, command-line tools, ASGI application, and interactive dashboard.

See [RELEASE_NOTES_0.1.3.md](RELEASE_NOTES_0.1.3.md) for the full changelog.

## Why I’m building eDocAPI

I’m building eDocAPI so Python developers can take a document from upload to useful text or a converted file through one clear workflow. I focus on the details that matter in real use: preserving page structure, handling uploads carefully, and making OCR easier to configure. I’ll keep refining these parts and add capabilities as practical use shows what should come next.

### Document workflow details in v0.1.3

- DOCX-to-PDF uses ReportLab's paginated layout engine, included in the core dependencies.
- DOCX conversion preserves centered cover titles, heading hierarchy, paragraph order, source table widths, and explicit page breaks.
- Contents pages use readable spacing and indentation for main sections and subsections.
- Tables have visible borders, dark readable text, emphasized first-column labels, and repeating header rows across page breaks.
- The interactive dashboard gives developers a feature summary and a single `/health` endpoint card for both GET and POST.
- Dashboard “Try it” responses, errors, and file previews appear in a modal without leaving the dashboard.
- ReportLab provides paginated DOCX-to-PDF output; the optional `html` extra adds HTML/Markdown PDF rendering.
- Missing, empty, encrypted, corrupt, and unsupported documents return stable framework errors; unexpected server errors do not expose exception text.
- HTML/Markdown/DOCX PDF rendering blocks local and remote resource access.
- Multipart uploads stream to managed temporary files under a separate total-request limit.

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

# OCR reads embedded PDF text directly and runs OCR only on scanned pages.
# Image OCR and scanned-page OCR require: pip install edocapi[ml]
text = Document("scan.png").ocr(lang="eng")

# Structured OCR for scanned pages, tables, and formula recognition
# Install with Python 3.13 or earlier: pip install edocapi[structured-ocr]
# Formula results are represented as Markdown/LaTeX where recognized.
# Choosing Paddle runs full layout and formula reconstruction, including
# text-based PDFs whose native text cannot represent stacked equations.
text = Document("exam.pdf").ocr(engine="paddle")

# Merge PDFs
merged = Document.merge(["a.pdf", "b.pdf"])

# Compress
small = Document("large.pdf").compress(target_size=500_000)
```

## Quick start (API server)

```python
# main.py
from edocapi import App, Document

# The framework accepts files up to 50MB by default.
app = App()

# Each service can choose a smaller upload limit.
# Values above 50MB are rejected by the framework.
uploads_app = App(max_file_size="10MB")

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

Supported Python versions are 3.10–3.13. Optional renderers and OCR engines are
installed through the documented extras; missing extras produce framework errors
or documented basic-renderer fallbacks.

### Upload limits

`App` accepts files up to **50MB** by default. Set `max_file_size` when creating
an app to use a smaller limit for a particular service. Integer values are bytes;
string values may use `KB` or `MB`.

```python
from edocapi import App

app = App(max_file_size="10MB")
```

The framework enforces 50MB as its highest permitted per-file limit. The total
request body has an independent 100MB default limit; configure it with
`max_request_size` when multipart overhead or multiple uploads require a different
budget. Oversized file and request bodies receive `413`. Missing uploads and
invalid documents receive `400`; unsupported types and signature mismatches
receive `415`. Unexpected server errors return a generic `500` response while
diagnostic details stay in server logs.

### Rate limits

Set a default rolling-window request limit per client, then add a stricter limit
to expensive routes. The built-in `/health` endpoint is exempt.

```python
from edocapi import App

app = App()
app.limits(100, per="minute")

@app.post("/convert", limit="10/minute")
def convert(file):
    ...

@app.post("/ocr", limit="3/minute")
def ocr(file):
    ...
```

The global limit remains an upper bound when a route limit is set. Requests over
the limit receive `429` and a `Retry-After` header. Client identity comes from
the ASGI connection IP; forwarded headers are not trusted. Limits are held in
the application process and are not shared between worker processes or servers.
Use a shared rate-limit store at the deployment layer when a distributed limit
across workers is required.

---

## Supported formats

This matrix lists operations implemented for each input type. It assumes a valid,
non-empty document and the optional packages or system tools described below.

| Input format | `to_pdf()` | `extract_text()` | `ocr()` | `compress()` | `merge()` | `to_images()` |
|---|---:|---:|---:|---:|---:|---:|
| PDF | Yes | Yes | Yes¹ | Yes | Yes² | Yes³ |
| DOCX | Yes | Yes | No | No | No | No |
| HTML / HTM | Yes⁴ | Yes | No | No | No | No |
| Markdown / MD | Yes⁴ | Yes⁷ | No | No | No | No |
| TXT | Yes | Yes | No | No | No | No |
| JPEG / JPG / PNG / WebP | Yes | Yes⁵ | Yes⁵ | Yes⁶ | No | No |

1. PDF `extract_text()` reads embedded text and needs no OCR extra. `ocr()` also
   returns embedded text for digital pages. Scanned pages using Tesseract require
   `edocapi[ml]` and the separately installed Tesseract executable; pages that
   need rendering may also require `edocapi[pdf-images]` and Poppler. The Paddle
   engine instead requires `edocapi[structured-ocr]`.
2. `merge()` accepts PDF inputs only.
3. PDF page rendering is provided by `to_images()` and requires
   `edocapi[pdf-images]` plus the Poppler system utility used by `pdf2image`.
4. HTML and Markdown can be converted with the built-in basic PDF renderer.
   Installing `edocapi[html]` enables WeasyPrint rendering. Linked local and
   remote resources are blocked in that renderer.
5. For images, `extract_text()` delegates to Tesseract OCR and requires
   `edocapi[ml]` plus the separately installed Tesseract executable;
   `Document.ocr(engine="paddle")` uses the optional
   `edocapi[structured-ocr]` extra instead.
6. Image compression is supported. When a target size is set, PNG compression
   may produce WebP or JPEG output to meet the target; check the returned
   document's `type` or file suffix.
7. Markdown `extract_text()` returns the original Markdown source, including
   formatting markers; it does not convert Markdown syntax to plain text.

The `Document.ocr()` library method is available independently of the ASGI
route setting. The ASGI `/ocr` route is disabled by default for applications
created with `App()`; enable it with `App(enable_ocr=True)`. The included
`main.py` example enables the route. Scanned images and PDF pages still require
the OCR dependencies described above.

## Optional extras

```bash
pip install edocapi[html]        # high-quality HTML/Markdown → PDF (WeasyPrint)
pip install edocapi[pdf-images]  # PDF → images (pdf2image)
pip install edocapi[ml]          # OCR + OpenCV pre-processing
pip install edocapi[structured-ocr] # Advanced PaddleOCR document recognition (Python <=3.13)
pip install edocapi[all]         # everything
pip install edocapi[server]      # uvicorn for running the App
```

PaddleOCR's advanced document pipeline requires Python 3.13 or earlier on
Windows. Python 3.14 skips the Paddle dependencies, so selecting PaddleOCR in
the dashboard cannot work under that interpreter. From this checkout, create a
separate Python 3.11 environment and launch the server with its interpreter:

```powershell
py -3.11 -m venv .venv-ocr
.\.venv-ocr\Scripts\python.exe -m ensurepip --upgrade
.\.venv-ocr\Scripts\python.exe -m pip install --upgrade pip
.\.venv-ocr\Scripts\python.exe -m pip install -e ".[structured-ocr,server]"
.\.venv-ocr\Scripts\python.exe -m edocapi.cli.main prefetch-ocr --lang en
.\.venv-ocr\Scripts\python.exe -m uvicorn main:app --reload
```

Python 3.11 is already available in this environment and PaddlePaddle publishes
a Windows wheel for it. If `py -3.11` is unavailable on another machine, install
64-bit Python 3.13 or earlier first. For a PyPI
installation, run `python -m pip install "edocapi[structured-ocr,server]"` from
the Python 3.11–3.13 environment that will run the server. PaddleOCR downloads its
model weights the first time you prefetch or run advanced OCR. Prefetch them before
serving requests with `edocapi prefetch-ocr --lang en`; this one-time download can
be several gigabytes, and PaddleX then reuses the local files. The prefetch command
and API server are separate processes, so the server still loads cached weights
into memory on its first OCR request. It keeps the initialized pipeline in memory
for later requests until the server restarts. Large chart parsing is optional and
off by default, so regular advanced OCR does not load the 2.26 GB Chart2Table
model. To enable chart-to-table recognition, set this variable before prefetching
and starting the server:

```powershell
$env:EDOCAPI_PADDLE_CHART_RECOGNITION = "1"
.\.venv-ocr\Scripts\python.exe -m edocapi.cli.main prefetch-ocr --lang en
.\.venv-ocr\Scripts\python.exe -m uvicorn main:app --reload
```

A hosted server shares its model cache among its users; each local installation
using PaddleOCR keeps its own cache. Users who select the default Tesseract engine
do not need the PaddleOCR models.

If Hugging Face is slow or unavailable, prefer Paddle's BOS mirror:

```powershell
edocapi prefetch-ocr --lang en --model-source bos --disable-model-source-check
```

The source-check option only skips PaddleX's connectivity precheck; the model
download still requires network access. The high-accuracy CPU models trade speed
for document recognition quality.

DOCX-to-PDF uses ReportLab's paginated layout engine, included in the core
dependencies. It preserves Word paragraph styling and renders tables with visible
borders.

---

## Security highlights

- Filenames are sanitized (basename only, dangerous characters stripped).
- Magic-byte verification prevents extension spoofing.
- A 50MB per-file ceiling, with configurable file-size and file-count limits.
- Multipart uploads stream to temporary files. A separate `max_request_size` limit defaults to 100MB and caps the full HTTP request, including multipart overhead.
- Uploads use generated, collision-resistant temporary names, and temporary cleanup is confined to registered paths under the storage root.
- Dashboard route metadata is HTML-escaped, route templates are validated, response filenames are encoded safely, and responses include baseline browser security headers.
- Temporary files are isolated and cleaned up automatically.
- Document contents are validated and processed as data before they enter a workflow.

---

## CLI

```bash
edocapi --version
edocapi convert report.docx -o report.pdf
edocapi extract report.pdf
edocapi info image.png
edocapi ocr scan.png --lang eng
edocapi ocr exam.pdf --engine paddle
edocapi prefetch-ocr --lang en
edocapi compress large.pdf --target 500KB
```

PDF compression removes duplicate objects and compresses content streams. When
you provide a target size, embedded opaque images are progressively downsampled
and re-encoded while selectable text is preserved. If that is not enough, pages
are rasterized and compressed as JPEG images to reduce text- and vector-heavy
documents too. Rasterized pages are no longer selectable or searchable, and
fine details may lose quality. The compressor returns the smallest result if it
still cannot reach the target; API responses report this with the
`X-Edocapi-Compression-Target-Met` header.

---

## License

MIT © EMMANUEL EMMANUEL ETIM
