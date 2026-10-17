"""Optional PaddleOCR document parser for layout and formula aware OCR."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from edocapi.exceptions import ProcessingError


@lru_cache(maxsize=2)
def _pipeline(language: str):
    if sys.version_info >= (3, 14):
        raise ProcessingError(
            f"Advanced PaddleOCR is unavailable in this Python {sys.version_info.major}."
            f"{sys.version_info.minor} environment: PaddlePaddle does not publish a "
            "compatible Windows runtime for it. Create a Python 3.13 or earlier environment, "
            "install this project with its structured OCR extra, and run the server "
            "from that environment. For this checkout: "
            'py -3.11 -m venv .venv-ocr, then run '
            '.\\.venv-ocr\\Scripts\\python.exe -m ensurepip --upgrade and '
            '.\\.venv-ocr\\Scripts\\python.exe -m pip install -e '
            '".[structured-ocr,server]". Start Uvicorn with that same interpreter.'
        )

    # Must be set before Paddle/PaddleX initialise their execution backend.
    # This avoids the unsupported oneDNN/PIR conversion path observed on
    # Windows CPU installations during formula and chart inference.
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")

    try:
        import paddle
        from paddleocr import PPStructureV3
    except ModuleNotFoundError as exc:
        # Only call it an absent optional extra when its public package is missing.
        # A missing dependency imported by paddleocr is a different problem and
        # should be visible to the user instead of being masked by this hint.
        if exc.name != "paddleocr":
            raise ProcessingError(
                f"PaddleOCR could not be imported because dependency '{exc.name}' "
                "is unavailable. In the Python environment running this server, "
                'install the project with: python -m pip install -e '
                '".[structured-ocr,server]".'
            ) from exc
        raise ProcessingError(
            "Structured OCR requires the optional 'structured-ocr' extra. "
            'Install it in the Python environment running this server with: '
            'python -m pip install -e ".[structured-ocr,server]".'
        ) from exc
    except ImportError as exc:
        raise ProcessingError(
            f"PaddleOCR is installed but could not be imported: {exc}. "
            'Reinstall the project extra in this server environment with: '
            'python -m pip install --force-reinstall -e ".[structured-ocr,server]".'
        ) from exc

    try:
        paddle.set_flags({"FLAGS_use_mkldnn": False, "FLAGS_enable_pir_api": False})
        # PP-StructureV3 provides document layout reconstruction alongside OCR.
        # The larger layout and server OCR models favor recognition quality
        # over speed. The server recognizer supports English as well as Chinese
        # and Japanese, so keep recognition quality consistent for English.
        model_options = {
            "layout_detection_model_name": "PP-DocLayout_plus-L",
            "text_detection_model_name": "PP-OCRv5_server_det",
            "text_recognition_model_name": "PP-OCRv5_server_rec",
        }
        chart_recognition = os.getenv(
            "EDOCAPI_PADDLE_CHART_RECOGNITION", ""
        ).strip().casefold() in {"1", "true", "yes", "on"}
        return PPStructureV3(
            lang=language,
            **model_options,
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True,
            use_table_recognition=True,
            use_formula_recognition=True,
            # Chart2Table is a large specialized model; load it only when a
            # deployment opts into chart-to-table extraction.
            use_chart_recognition=chart_recognition,
            use_seal_recognition=True,
            device="cpu",
            # PaddlePaddle 3.3.x can crash in the CPU oneDNN/PIR path with
            # `ConvertPirAttribute2RuntimeAttribute` during prediction.
            # Keep inference on the standard CPU backend for compatibility.
            enable_mkldnn=False,
        )
    except Exception as exc:
        raise ProcessingError(f"Could not initialize PaddleOCR document models: {exc}") from exc


def ocr_document(path: Path, *, lang: str = "eng") -> str:
    """Return structured Markdown from a scanned image or PDF."""
    # PP-StructureV3 uses ISO-style names instead of Tesseract's three-letter codes.
    language = {"eng": "en", "en-us": "en", "en-gb": "en"}.get(lang.casefold(), lang)
    pipeline = _pipeline(language)
    try:
        results = pipeline.predict(input=str(path))
        markdown_pages = [result.markdown for result in results]
        text = pipeline.concatenate_markdown_pages(markdown_pages)
    except Exception as exc:
        raise ProcessingError(f"Structured OCR failed: {exc}") from exc
    if isinstance(text, dict):
        text = text.get("markdown_text", text.get("text", ""))
    return str(text).strip()
