# Publishing eDocAPI 0.2.0 to PyPI

## 1. Install build tools

```bash
python -m pip install --upgrade build twine
```

## 2. Run checks and build

```bash
python -m pytest
python -m build --outdir dist-0.2.0
python -m twine check dist-0.2.0/*
```

This creates the 0.2.0 source distribution and wheel in `dist-0.2.0/`.

## 3. Test the package (optional)

```bash
python -m twine upload --repository testpypi dist-0.2.0/*
python -m pip install --index-url https://test.pypi.org/simple/ edocapi==0.2.0
```

## 4. Upload to PyPI

```bash
python -m twine upload dist-0.2.0/*
```

Use a PyPI API token when Twine prompts for credentials. After upload, verify the project page and that `python -m pip install edocapi==0.2.0` works.

## Release checklist

- Confirm `pyproject.toml`, `edocapi.__version__`, the README badge, and `RELEASE_NOTES_0.2.0.md` all say 0.2.0.
- Check that the source archive contains `README.md`, `LICENSE`, and `RELEASE_NOTES_0.2.0.md`.
- Run the test suite, build both distributions, and run `twine check`.
- Push the release commit and wait for the GitHub Actions matrix to pass before uploading to PyPI.
- PyPI's version badge reflects the latest version published there, not the version in GitHub source. The README uses a static source release badge so it won't display an old cached PyPI version.
