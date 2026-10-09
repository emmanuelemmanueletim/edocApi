# Publishing eDocAPI v0.0.1 to PyPI

## Package is ready

Built artifacts:

```
dist/edocapi-0.0.1.tar.gz
dist/edocapi-0.0.1-py3-none-any.whl
```

## One-time setup

1. Create an account on https://pypi.org (and optionally https://test.pypi.org)
2. Create an API token: Account settings → API tokens → Add API token
3. Install tools:

```bash
pip install build twine
```

## Test upload (recommended first)

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Install from TestPyPI to verify
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ edocapi==0.0.1
```

## Production upload

```bash
python -m twine upload dist/*
```

You will be prompted for username `__token__` and password = your API token.

## After publish

```bash
pip install edocapi
# or with PDF conversion extras:
pip install edocapi[html]
pip install edocapi[all]
```

## Rebuild (if you change code)

```bash
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*
```

## Notes

- Core install does **not** require WeasyPrint (heavy / system libs).
- HTML/Markdown/DOCX → PDF needs `pip install edocapi[html]` plus system packages (cairo, pango, gdk-pixbuf).
- PDF → images needs `pip install edocapi[pdf-images]` and poppler-utils.
- CLI entry point: `edocapi run`
- License: MIT
