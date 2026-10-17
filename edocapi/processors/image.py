"""Image processor for eDocAPI – compression, conversion & ML OCR."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter

from edocapi.exceptions import InvalidDocument, ProcessingError
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.processors.ocr import configure_tesseract, normalize_tesseract_language

logger = logging.getLogger("edocapi.processors.image")


@register_processor("jpeg", "jpg", "png", "webp")
class ImageProcessor(BaseProcessor):
    supported_input_types = {"jpeg", "jpg", "png", "webp"}
    supported_output_types = {"pdf", "png", "jpg", "webp", "txt"}

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        super().__init__(path, temp_storage=temp_storage)
        try:
            self._img = Image.open(str(path))
            self._img.load()
        except Exception as exc:
            raise InvalidDocument(f"Invalid or corrupted image: {exc}") from exc

    def to_pdf(self) -> Path:
        out = self._temp_path(suffix=".pdf", prefix="img_")
        img = self._img.convert("RGB") if self._img.mode in ("RGBA", "P", "LA") else self._img
        img.save(str(out), "PDF", resolution=100.0)
        return out

    def to_text(self) -> str:
        """OCR the image (requires ml extra)."""
        return self.ocr()

    def ocr(self, *, lang: str = "eng") -> str:
        """ML-powered OCR using Tesseract (+ optional OpenCV pre-processing)."""
        try:
            import pytesseract
        except ImportError as exc:
            raise ProcessingError(
                "OCR requires the 'ml' extra. Install with: pip install edocapi[ml]"
            ) from exc

        configure_tesseract(pytesseract)
        lang = normalize_tesseract_language(lang)

        img = self._img
        # Optional OpenCV pre-processing for better accuracy
        try:
            import cv2
            import numpy as np
            arr = np.array(img.convert("RGB"))
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            # Adaptive thresholding + mild denoise
            gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            img = Image.fromarray(thresh)
            logger.debug("Applied OpenCV pre-processing for OCR")
        except ImportError:
            # Enhance contrast with Pillow only
            img = ImageEnhance.Contrast(img.convert("L")).enhance(1.5)

        try:
            text = pytesseract.image_to_string(img, lang=lang)
        except Exception as exc:
            raise ProcessingError(f"OCR failed: {exc}") from exc
        return text.strip()

    def compress(self, target_size: int | None = None) -> Path:
        """Smart image compression with quality iteration toward target size."""
        fmt = self.path.suffix.lower().lstrip(".")
        if fmt == "jpg":
            fmt = "jpeg"
        out_fmt = fmt if fmt in {"jpeg", "png", "webp"} else "jpeg"
        out = self._temp_path(suffix=f".{out_fmt if out_fmt != 'jpeg' else 'jpg'}", prefix="compressed_")

        img = self._img
        if out_fmt == "jpeg" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        quality = 85
        if target_size:
            # Binary search quality
            low, high = 10, 95
            best = None
            for _ in range(8):
                quality = (low + high) // 2
                buf = out  # write to same path
                save_kwargs: dict[str, Any] = {"format": out_fmt.upper()}
                if out_fmt in {"jpeg", "webp"}:
                    save_kwargs["quality"] = quality
                    save_kwargs["optimize"] = True
                img.save(str(buf), **save_kwargs)
                size = buf.stat().st_size
                if size <= target_size:
                    best = quality
                    low = quality + 1
                else:
                    high = quality - 1
            quality = best or 40
        else:
            save_kwargs = {"format": out_fmt.upper(), "optimize": True}
            if out_fmt in {"jpeg", "webp"}:
                save_kwargs["quality"] = quality
            img.save(str(out), **save_kwargs)
            return out

        save_kwargs = {"format": out_fmt.upper(), "optimize": True}
        if out_fmt in {"jpeg", "webp"}:
            save_kwargs["quality"] = quality
        img.save(str(out), **save_kwargs)
        logger.info("Compressed image %s → %s bytes (q=%s)", self.path.name, out.stat().st_size, quality)
        return out

    def info(self) -> dict[str, Any]:
        base = super().info()
        base.update({
            "width": self._img.width,
            "height": self._img.height,
            "mode": self._img.mode,
            "format": self._img.format,
        })
        return base

    def enhance(self, *, sharpness: float = 1.2, contrast: float = 1.1) -> Path:
        """Simple ML-friendly image enhancement before conversion/OCR."""
        img = ImageEnhance.Sharpness(self._img).enhance(sharpness)
        img = ImageEnhance.Contrast(img).enhance(contrast)
        out = self._temp_path(suffix=self.path.suffix, prefix="enhanced_")
        img.save(str(out))
        return out
