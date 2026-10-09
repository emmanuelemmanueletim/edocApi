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

## Publish

Use a PyPI API token and Trusted Publishing where configured. Otherwise upload
with Twine, entering `__token__` as the username and the token as the password:

```bash
python -m twine upload dist/*
```

Do not commit API tokens. A version already uploaded to PyPI cannot be replaced;
increment the version for every follow-up release.

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
