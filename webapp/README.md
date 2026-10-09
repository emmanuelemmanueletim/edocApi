# eDocAPI Web Application

Landing page + dashboard built on **eDocAPI**.

## Run

```bash
# From repo root — install the framework and web template dependency
py -m pip install -e .

# Web app dependency
py -m pip install -r webapp/requirements.txt

# Start
py -m edocapi.cli.main run webapp.main:app --reload --host 127.0.0.1 --port 8001
```

Or:

```bash
py -m edocapi.cli.main run webapp.main:app --reload --host 127.0.0.1 --port 8001
```

Open:

- http://127.0.0.1:8001 — landing
- http://127.0.0.1:8001/dashboard — tools UI
- http://127.0.0.1:8001/docs-ui — usage notes

## Dashboard tools

| Tool | API |
|------|-----|
| Convert to PDF | `POST /api/convert` |
| Extract text | `POST /api/extract` |
| Compress PDF | `POST /api/compress` |
| Merge PDFs | `POST /api/merge` |
| Split / extract pages | `POST /api/split-info`, `POST /api/extract-pages` |
| Document info | `POST /api/info` |
| HTML → PDF | `POST /api/html-to-pdf` |
| Markdown → PDF | `POST /api/markdown-to-pdf` |

All document work goes through `edocapi.Document`.
