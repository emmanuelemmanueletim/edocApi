# Release checklist

This document describes the release process. Publishing requires the maintainer's
PyPI credentials and is a separate step from preparing the package.

## Before release

1. Update the version in `pyproject.toml`, `edocapi/__init__.py`, and README.
2. Review the changes and run the project test suite on supported Python versions.
3. Build and inspect both distributions:

   ```bash
   python -m pip install --upgrade build twine
   python -m build
   python -m twine check dist/*
   ```

4. Install the wheel in a clean environment and verify `import edocapi`, the
   `edocapi --version` command, and the documented optional extras.
5. Upload to TestPyPI and install the candidate package from a clean environment.

## eDocAPI 0.1.0 release notes

### Highlights

- Add an automatically generated developer dashboard at `/` showing the app's
  registered routes, supported document formats, upload limit, and document
  operations.
- Keep a developer-defined `GET /` route in control; disable the built-in
  dashboard with `App(dashboard=False)`.
- Document the local development server workflow and dashboard URL.

### Compatibility

- This release remains alpha software and keeps the existing document
  conversion API and optional dependency model.
- Dashboard behavior is additive for apps without a `GET /` route.

### GitHub release note

Create a GitHub release for tag `v0.1.0` with title `eDocAPI 0.1.0` and use
the contents of [RELEASE_NOTES_0.1.0.md](RELEASE_NOTES_0.1.0.md) as its body.
Publish the source tag and GitHub release after the TestPyPI candidate has
been reviewed.

### TestPyPI note

This is a **TestPyPI candidate** for validating the 0.1.0 package build and
installation. TestPyPI is a separate test index; installing from it may require
specifying `--index-url https://test.pypi.org/simple/` and the production PyPI
index as `--extra-index-url` for dependencies. This candidate note does not
announce a production PyPI release.

### Build, check, and upload to TestPyPI

Build from a clean distribution directory, then check and upload explicitly to
the TestPyPI repository:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
```

Confirm the artifacts are named `edocapi-0.1.0.tar.gz` and
`edocapi-0.1.0-py3-none-any.whl`. Do not upload these same artifacts to the
production PyPI repository unless you intend to make the public release.

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
