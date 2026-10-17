# eDocAPI 0.1.2

**Release date:** 2026-10-17  
**Focus:** reliability, security, and release quality

## Security and reliability

- Reject missing uploads, empty document handles, empty converter output, malformed documents, encrypted PDFs, and unsupported operations with predictable framework errors.
- Validate extension, file size, text encoding, and content signatures; reject MIME/signature mismatches and binary content disguised as text.
- Block local and remote resource fetches during HTML, Markdown, and DOCX PDF rendering.
- Stream multipart uploads into managed temporary files under independent per-file and total-request limits.
- Stream file responses in chunks and clean managed files after sending, including interrupted sends.
- Use private permissions for generated temporary files and clean partial conversion outputs on failure.
- Return generic internal errors to clients while keeping diagnostic details in server logs.

## Configuration and API

- Apply configured extension allowlists and strict signature checking to uploads.
- Add the independently configurable `max_request_size` limit (100 MiB default).
- Apply OCR enablement and default language configuration to matching OCR handlers.
- Validate every merge input as an unencrypted, readable PDF before merging.
- Add a per-client global rolling-window limiter and per-route overrides; `/health` is exempt.
- Return `429` with `Retry-After` when a client exceeds its configured budget.

## Release engineering

- Add CI across supported Python 3.10–3.13 versions on Ubuntu and Windows, with package build checks and optional-extra installation checks.
- Add regression tests for upload, conversion, rendering, validation, response streaming, and cleanup failures.
- Ignore and remove generated `.pytest-run-*` artifacts.


## Credits

Built and maintained by **EMMANUEL EMMANUEL ETIM**.
