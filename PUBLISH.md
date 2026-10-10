# Release checklist

This document describes the release process. Publishing requires the maintainer's
PyPI credentials and is a separate step from preparing the package.

## Before release

This change set intentionally keeps the package version at **0.1.0**. First
check whether that version has already been published to PyPI and whether the
GitHub tag `v0.1.0` already exists. PyPI versions cannot be overwritten. If
either release already exists, do not reuse its version; prepare a new version
before publishing.

1. Review the pending changes and release notes.
2. Run the project's checks on supported Python versions.
3. Build and inspect both distributions:

   ```bash
   python -m pip install --upgrade build twine
   python -m build
   python -m twine check dist/*
   ```

4. Install the wheel in a clean environment and verify `import edocapi`, the
   `edocapi --version` command, and the documented optional extras.
5. Build and verify a candidate locally. Upload to TestPyPI only if you want a
   separate pre-release check; it is not required for the production upload.

## eDocAPI 0.1.0 release notes

Use [RELEASE_NOTES_0.1.0.md](RELEASE_NOTES_0.1.0.md) as the detailed GitHub
release description. This update includes the built-in developer dashboard,
PDF and image compression, safer image type checking, document conversion
fallbacks, and improvements to the separate example company web application.

### GitHub release note

Create a GitHub release for tag `v0.1.0` with title `eDocAPI 0.1.0` and use
the contents of [RELEASE_NOTES_0.1.0.md](RELEASE_NOTES_0.1.0.md) as its body.

### PyPI release note

The source metadata remains at version 0.1.0. Confirm that this exact version
is not already published before uploading. It includes the built-in developer
dashboard and API explorer, target-size PDF compression, JPG/JPEG/PNG/WebP
compression, conversion fallback support, and the standalone example company
site under `webapp/`.

### Build, check, and upload to PyPI

Build from a clean distribution directory and check the files. Only upload if
PyPI confirms `0.1.0` is still available:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
# Run only after confirming the version is not already published:
python -m twine upload dist/*
```

Confirm the artifacts are `edocapi-0.1.0.tar.gz` and
`edocapi-0.1.0-py3-none-any.whl`. Do not upload stale artifacts from older
versions. If those filenames already exist on PyPI, stop and bump the package
version for a follow-up release.

## Publish

Use a PyPI API token and Trusted Publishing where configured. Otherwise upload
with Twine, entering `__token__` as the username and the token as the password:

```bash
python -m twine upload dist/*
```

Do not commit API tokens. A version already uploaded to PyPI cannot be replaced;
increment the version for every follow-up release.

For an upload, build with an empty `dist/` directory so the command cannot
accidentally include stale artifacts from an earlier version. Verify the
filenames match the intended release version before uploading.

## Hosted deployment

Create an application module exposing `app = App()` and run an ASGI server, for
example:

```bash
uvicorn main:app.asgi --host 0.0.0.0 --port ${PORT:-8000} --workers 2
```

Use `debug=False`, configure the proxy body-size limit to match the app's upload
limit, and install the required operating-system libraries for optional PDF
conversions. Monitor temporary disk usage and use a queue for CPU-heavy or
long-running document conversions.
