# Publishing eDocAPI 0.1.2 to PyPI

## 1. Install build tools

```bash
pip install --upgrade build twine
```

## 2. Build the distribution

```bash
cd /path/to/edocapi
python -m build
```

This produces the 0.1.2 source distribution and wheel.

## 3. Check the package

```bash
twine check dist/*
```

## 4. Upload to TestPyPI (recommended first)

```bash
twine upload --repository testpypi dist/*
```

Then test:

```bash
pip install -i https://test.pypi.org/simple/ edocapi==0.1.2
```

## 5. Upload to production PyPI

```bash
twine upload dist/*
```

After a few minutes:

```bash
pip install edocapi
```

## Notes

- Make sure `LICENSE`, `README.md`, and `RELEASE_NOTES_0.1.2.md` are present.
- Version is defined in `pyproject.toml` and `edocapi/__init__.py`.
- Run `python -m pytest`, `python -m build`, and `python -m twine check dist/*` before publishing.
- Verify optional extras with `python -m pip install -e ".[html,pdf-images,ml,structured-ocr,server]"` on a supported Python version.
- Confirm release notes, README, supported Python versions, and installation instructions agree.
- Push the release commit and wait for the Ubuntu/Windows CI matrix and distribution checks to pass before creating the `v0.1.2` GitHub release or uploading to PyPI.
