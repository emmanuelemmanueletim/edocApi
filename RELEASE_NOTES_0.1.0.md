# eDocAPI 0.1.0

This update keeps the package version at **0.1.0** and improves document
compression, conversion reliability, developer onboarding, and the example web
application.

## Highlights

- Add a built-in developer dashboard at `/` for apps without their own `GET /`
  route. It lists registered routes and supported formats, and provides an API
  explorer for trying endpoints.
- Support compression through `Document.compress()` and the example API for
  PDF, JPG/JPEG, PNG, and WebP. Image downloads retain their image format.
- Add optional target-size compression in KB or MB, with output size reporting
  and warnings when PDF text reflow is needed to meet a requested limit.
- Validate supported image extensions against file contents and return a clear
  error for mismatched image signatures.
- Improve PDF compression compatibility with current pypdf versions.
- Add a text-based PDF rendering fallback for HTML, Markdown, TXT, and DOCX
  conversion when WeasyPrint's native libraries are unavailable.
- Improve the standalone company web app dashboard, compression feedback,
  format-specific downloads, and Windows setup documentation.

## Compatibility and limitations

- The package version and release tag remain `0.1.0` (`v0.1.0`).
- PDF text reflow can simplify layout and remove graphics; image-only scanned
  PDFs may not have extractable text for this fallback.
- Image compression is lossy when required to reduce size. PNG transparency is
  preserved, but quantization can reduce color detail.
- The conversion fallback produces readable, paginated text but does not retain
  the original document styling. Install WeasyPrint and its system libraries
  for richer HTML-based layouts.

## Run locally

Install the project and run the framework example dashboard:

```powershell
py -m pip install -e .
py -m edocapi.cli.main run main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/`. The separate company web app runs with
`py -m edocapi.cli.main run webapp.main:app --reload --port 8000`; open
`http://127.0.0.1:8000/` for its home page and `/dashboard` for its tools.

## GitHub and PyPI

Use this note as the GitHub release description for tag `v0.1.0`. Build fresh
artifacts from this source and inspect them before any PyPI upload. PyPI does
not allow replacing files for a version that has already been published; check
whether `0.1.0` is available before uploading. If it is already published,
prepare a new version instead of attempting to reuse the version number.
