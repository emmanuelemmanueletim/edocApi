# Publishing eDocAPI 0.1.3 to PyPI

## 1. Install build tools

```bash
pip install --upgrade build twine
```

## 2. Build the distribution

```bash
cd /path/to/edocapi
python -m build --outdir dist-0.1.3
```

This produces the 0.1.3 source distribution and wheel in `dist-0.1.3/`.

## 3. Check the package

```bash
twine check dist-0.1.3/*
```

## 4. Upload to TestPyPI (recommended first)

```bash
twine upload --repository testpypi dist-0.1.3/*
```

Then test:

```bash
pip install -i https://test.pypi.org/simple/ edocapi==0.1.3
```

## 5. Upload to production PyPI

```bash
twine upload dist-0.1.3/*
```

After a few minutes:

```bash
pip install edocapi
```

## Notes

- Make sure `LICENSE`, `README.md`, and `RELEASE_NOTES_0.1.3.md` are present.
- Version is defined in `pyproject.toml` and `edocapi/__init__.py`.
- Run `python -m pytest`, `python -m build`, and `python -m twine check dist/*` before publishing.
- Verify optional extras with `python -m pip install -e ".[html,pdf-images,ml,structured-ocr,server]"` on a supported Python version.
- Confirm release notes, README, supported Python versions, and installation instructions agree.
- This is a documentation and packaging metadata release; it refreshes the README PyPI embeds. The uploaded 0.1.3 metadata will be immutable, so verify its README badge and version references before upload.
- Push the release commit and wait for the Ubuntu/Windows CI matrix and distribution checks to pass before creating the `v0.1.3` GitHub release or uploading to PyPI.
