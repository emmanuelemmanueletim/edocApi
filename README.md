# eDocAPI

**A lightweight Python framework for building document-processing and document-automation APIs.**

> Simple API for the developer. Powerful document processing underneath.

Built on [Starlette](https://www.starlette.io/). Version **0.1.0**.

---

## Installation

**Core** (PDF, DOCX text/HTML, images, Markdown text/HTML, uploads, CLI):

```bash
pip install edocapi
```

**With enhanced HTML/Markdown/DOCX → PDF layout** (pulls in WeasyPrint):

```bash
pip install edocapi[html]
```

WeasyPrint may need system libraries for enhanced layout. On Debian/Ubuntu:

```bash
sudo apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
  libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info
```

**With PDF → images** (requires poppler):

```bash
pip install edocapi[pdf-images]
# system: sudo apt-get install -y poppler-utils
```

**Everything:**

```bash
pip install edocapi[all]
```

**Development (from source):**

```bash
pip install -e ".[dev,html]"
```

## Build and publish

From the repository root, build and check the package before uploading:

```powershell
py -m pip install --upgrade build twine
py -m build
py -m twine check dist/*
py -m twine upload dist/*
```

Use `__token__` as the Twine username and your PyPI API token as the password
when prompted. Do not commit the token. See [PUBLISH.md](PUBLISH.md) for the
full checklist.

---

## Quick Start

Create `main.py`:

```python
from edocapi import App, Document

app = App()

@app.post("/convert")
def convert(file):
    return Document(file).to_pdf()

@app.post("/compress")
def compress(file):
    return Document(file).compress()

@app.post("/extract")
def extract(file):
    return {"text": Document(file).extract_text()}

@app.post("/merge")
def merge(files):
    return Document.merge(files)

@app.get("/")
def home():
    return {"message": f"eDocAPI v{__version__}", "supported": Document.supported_types()}
```

Run the development server:

```bash
edocapi run
# or with auto-reload:
edocapi run --reload
```

Open **http://127.0.0.1:8000** in your browser to see the eDocAPI developer dashboard for your app. It shows your registered routes, supported document types, upload limit, and available `Document` operations, with a Try it explorer for testing endpoints. The dashboard is enabled by default when you have not registered your own `GET /` route. Set `App(dashboard=False)` to disable it. The separate eDocAPI company site lives in `webapp/`; see [webapp/README.md](webapp/README.md) to run it.

Upload a document to `POST /convert` and receive a PDF.

---

## Core Concepts

### Application

```python
from edocapi import App

app = App(
    debug=True,
    max_file_size="25MB",
)
```

### Document

```python
from edocapi import Document

# From uploaded file (Path)
doc = Document(file)

# From HTML string
doc = Document.html("<h1>Invoice</h1><p>Total: ₦50,000</p>")

# From Markdown
doc = Document.markdown("# Hello World")
```

### Conversions

```python
Document(file).to_pdf()          # → Document (PDF)
Document(file).to_text()         # → str
Document(file).extract_text()    # → str
Document(file).to_html()         # → str
Document(file).to_images()       # → list[Document]
```

### PDF Operations

```python
Document(file).compress(level="medium")
Document(file).split()                    # list of single-page Documents
Document(file).extract_pages(1, 5)        # 1-based inclusive
Document(file).rotate(90, pages=[1, 2])
Document.merge([file1, file2])
Document(file).info()                     # dict of metadata
```

`Document(file).compress(target_size=20 * 1024, level="medium")` optionally
targets a maximum output size in bytes. PDFs are optimized and their output
size is checked; text-based PDFs can be rebuilt with simplified layout and
without original graphics if needed. Image files with JPG/JPEG, PNG, or WebP
extensions are recompressed and retain their image format. Image compression
can reduce color detail. Some target sizes cannot be reached. Without a
target, the compressor returns the original if recompression would make it
larger. Other document types are not accepted by `compress()`.

---

## Supported Formats

| Input     | to_pdf | to_text | to_html | to_images | Notes                  |
|-----------|--------|---------|---------|-----------|------------------------|
| PDF       | ✓      | ✓       | ✓*      | ✓**       | *text-based HTML       |
| DOCX      | ✓      | ✓       | ✓       | –         |                        |
| HTML      | ✓      | ✓       | ✓       | –         |                        |
| Markdown  | ✓      | ✓       | ✓       | –         |                        |
| JPG/PNG/WEBP | ✓   | –       | –       | ✓         |                        |
| TXT       | –      | ✓       | –       | –         | via Document constructor |

\* PDF→HTML is a simple text extraction wrapper, not a visual rendering.  
\*\* PDF→Images requires optional `pdf2image` + system poppler.

---


## Deploying

The package exposes an ASGI application. In your application's `main.py`, create
`app = App()` and start it with an ASGI server. For example:

```bash
uvicorn main:app.asgi --host 0.0.0.0 --port ${PORT:-8000} --workers 2
```

Keep `debug=False` in hosted environments. HTML, Markdown, TXT, and DOCX PDF
conversion have a Pillow text-rendering fallback; install WeasyPrint's
operating-system libraries for richer layout. Set the reverse proxy's request-body limit to match
`max_file_size`; for larger workloads, use a worker queue and monitor temporary
disk usage.

## Configuration

```python
app = App(
    debug=False,           # more detailed errors when True
    max_file_size="10MB",  # "10MB", "25MB", 10485760, etc.
    temp_dir=None,         # custom temp directory (optional)
)
```

---

## Error Handling

eDocAPI raises specific exceptions that become consistent JSON responses:

```json
{
  "error": "UnsupportedFileType",
  "message": "The uploaded file type is not supported. (extension: .xlsx)"
}
```

Available exceptions: `EdocAPIError`, `UnsupportedFileType`, `InvalidDocument`, `FileTooLarge`, `FileNotFound`, `ConversionError`, `ProcessingError`, `ValidationError`.

---

## CLI

```bash
edocapi --version
edocapi run                  # main:app on http://0.0.0.0:8000
edocapi run --reload
edocapi run myapp:app --port 8080
```

---

## Architecture

```
eDocAPI
   │
   Document abstraction
   │
   +───────────+───────────+
   │           │           │
  PDF        DOCX        Images …
   │           │           │
 pypdf    python-docx   Pillow
              │
         weasyprint (HTML/PDF)
```

Processors are registered internally and can be extended in future versions.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

---


## Release status

eDocAPI is alpha software. Review conversion behavior, optional system
dependencies, and workload limits before exposing it to untrusted public
traffic. See [PUBLISH.md](PUBLISH.md) for the release checklist.

## Roadmap

- **v0.1** – OpenAPI generation, more formats, plugin system  
- **v0.2** – OCR, background jobs, cloud storage adapters  
- **v0.3+** – Document signing, AI integrations, advanced workflows  

---

## Author

**EMMANUEL EMMANUEL ETIM**  
Email: [emmanuel224etim089@gmail.com](mailto:emmanuel224etim089@gmail.com)  
GitHub: [https://github.com/emmanuelemmanueletim/edocApi](https://github.com/emmanuelemmanueletim/edocApi)

---

## License

MIT — Copyright (c) 2026 EMMANUEL EMMANUEL ETIM
