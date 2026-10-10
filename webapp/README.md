# eDocAPI Web Application

Landing page + dashboard built on **eDocAPI**.

## Run

```bash
# From repo root — install the framework and web template dependency
py -m pip install -e .

# Web app dependency
py -m pip install -r webapp/requirements.txt

# Start the company site and tools on port 8000
py -m edocapi.cli.main run webapp.main:app --reload --host 127.0.0.1 --port 8000
```

Or:

```bash
py -m edocapi.cli.main run webapp.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

- http://127.0.0.1:8000 — landing page
- http://127.0.0.1:8000/dashboard — document tools
- http://127.0.0.1:8000/docs-ui — usage notes

## Dashboard tools

| Tool | API |
|------|-----|
| Convert to PDF | `POST /api/convert` |
| Extract text | `POST /api/extract` |
| Compress PDF and images | `POST /api/compress` |
| Merge PDFs | `POST /api/merge` |
| Split / extract pages | `POST /api/split-info`, `POST /api/extract-pages` |
| Document info | `POST /api/info` |
| HTML → PDF | `POST /api/html-to-pdf` |
| Markdown → PDF | `POST /api/markdown-to-pdf` |

All document work goes through `edocapi.Document`.

The compression tool accepts PDF, JPG, JPEG, PNG, and WebP files and supports
an optional target size and unit (KB or MB). For
example: `/api/compress?target_size_value=20&target_unit=MB`. Image downloads
retain their image extension. PDF compression optimizes embedded content; if
needed to meet a target, a text-based PDF may be rebuilt with simplified layout
and without original graphics. Scanned PDFs may not have extractable text, so
every target size cannot be guaranteed. Image compression may reduce color
detail. Other file types are rejected by the compression endpoint.

### PDF conversion on Windows

HTML, Markdown, TXT, and DOCX to PDF work without extra system setup. When
WeasyPrint and its native libraries are available, eDocAPI uses them for richer
layout. If Windows cannot load GTK, the framework automatically creates a
readable, paginated PDF from the document text using Pillow. The fallback
preserves text content, but not the original styling or selectable text.
