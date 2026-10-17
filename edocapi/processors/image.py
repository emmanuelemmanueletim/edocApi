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
        """Compress an image, reducing quality and dimensions to meet a byte target.

        When a target is supplied, PNG inputs may be returned as JPEG or WebP if
        lossless PNG optimization cannot reach it. If the requested target is
        below the smallest practical encoding, the smallest candidate is returned.
        """
        fmt = self.path.suffix.lower().lstrip(".")
        if fmt == "jpg":
            fmt = "jpeg"
        out_fmt = fmt if fmt in {"jpeg", "png", "webp"} else "jpeg"
        out = self._temp_path(suffix=f".{out_fmt if out_fmt != 'jpeg' else 'jpg'}", prefix="compressed_")
        source = self._img.copy()
        if target_size is None:
            self._save_candidate(source, out_fmt, out, quality=85)
            return out
        if target_size <= 0:
            raise ProcessingError("Image compression target must be greater than zero bytes.")

        # Keep alpha for PNG/WebP. JPEG candidates use RGB on a white background.
        candidates = [out_fmt]
        if out_fmt == "png":
            candidates.extend(["webp", "jpeg"])
        best_size: int | None = None
        best_tmp: Path | None = None
        best_fmt = out_fmt

        # Re-encode at progressively smaller dimensions. A target can be
        # unattainable at original dimensions regardless of JPEG quality.
        for candidate_fmt in candidates:
            img = source
            if candidate_fmt == "jpeg" and img.mode in ("RGBA", "P", "LA"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                img = background
            elif candidate_fmt == "jpeg" and img.mode != "RGB":
                img = img.convert("RGB")

            scale = 1.0
            while True:
                width = max(1, round(source.width * scale))
                height = max(1, round(source.height * scale))
                resized = img if img.size == (width, height) else img.resize(
                    (width, height), Image.Resampling.LANCZOS
                )
                qualities = [90, 80, 70, 60, 50, 40, 30, 20, 10] if candidate_fmt in {"jpeg", "webp"} else [None]
                candidate_path = self._temp_path(
                    suffix=f".{candidate_fmt if candidate_fmt != 'jpeg' else 'jpg'}",
                    prefix="image_candidate_",
                )
                for quality in qualities:
                    self._save_candidate(resized, candidate_fmt, candidate_path, quality=quality)
                    size = candidate_path.stat().st_size
                    if best_size is None or size < best_size:
                        if best_tmp is not None:
                            best_tmp.unlink(missing_ok=True)
                        best_size, best_tmp, best_fmt = size, candidate_path, candidate_fmt
                        candidate_path = self._temp_path(
                            suffix=f".{candidate_fmt if candidate_fmt != 'jpeg' else 'jpg'}",
                            prefix="image_candidate_",
                        )
                    if size <= target_size:
                        candidate_path.unlink(missing_ok=True)
                        out = self._temp_path(
                            suffix=f".{candidate_fmt if candidate_fmt != 'jpeg' else 'jpg'}",
                            prefix="compressed_",
                        )
                        self._save_candidate(resized, candidate_fmt, out, quality=quality)
                        logger.info("Compressed image %s to %s bytes (%s, %sx%s, q=%s)", self.path.name, out.stat().st_size, candidate_fmt, width, height, quality)
                        if best_tmp is not None:
                            best_tmp.unlink(missing_ok=True)
                        return out
                candidate_path.unlink(missing_ok=True)
                if width == 1 and height == 1:
                    break
                scale *= 0.8

        if best_tmp is None:
            raise ProcessingError("Unable to encode image for compression.")
        # Return the smallest candidate even when the requested limit cannot be
        # reached (for example, a 1x1 image with a target below format overhead).
        best_tmp.replace(out)
        logger.info("Compressed image %s to minimum %s bytes (%s; requested %s)", self.path.name, best_size, best_fmt, target_size)
        return out

    @staticmethod
    def _save_candidate(img: Image.Image, fmt: str, path: Path, *, quality: int | None) -> None:
        save_fmt = fmt.upper()
        kwargs: dict[str, Any] = {"format": save_fmt}
        if fmt == "png":
            kwargs.update(optimize=True, compress_level=9)
        elif fmt in {"jpeg", "webp"}:
            kwargs.update(quality=quality or 10, optimize=(fmt == "jpeg"))
        img.save(str(path), **kwargs)

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
