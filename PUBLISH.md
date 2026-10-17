# Publishing eDocAPI 0.1.1 to PyPI

## 1. Install build tools

```bash
pip install --upgrade build twine
```

## 2. Build the distribution

```bash
cd /path/to/edocapi
python -m build
```

This produces:
- `dist/edocapi-0.1.1.tar.gz`
- `dist/edocapi-0.1.1-py3-none-any.whl`

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
pip install -i https://test.pypi.org/simple/ edocapi==0.1.1
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

- Make sure `LICENSE`, `README.md`, and `RELEASE_NOTES_0.1.1.md` are present.
- Version is defined in `pyproject.toml` and `edocapi/__init__.py`.
- Check that package capabilities, installation extras, and README guidance match before publishing.
