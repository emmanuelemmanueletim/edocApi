"""Image processor for eDocAPI (uses Pillow + weasyprint / reportlab-like via PDF)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

from edocapi.exceptions import ConversionError, InvalidDocument
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi.processors.image")


@register_processor("jpeg", "jpg", "png", "webp")
class ImageProcessor(BaseProcessor):
    """Processor for common image formats."""

    supported_input_types = {"jpeg", "jpg", "png", "webp"}
    supported_output_types = {"pdf", "png", "jpg", "webp"}

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        super().__init__(path, temp_storage=temp_storage)
        try:
            self._img = Image.open(str(path))
            self._img.load()  # force load to validate
        except Exception as exc:
            raise InvalidDocument(f"Invalid or corrupted image: {exc}") from exc

    def to_pdf(self) -> Path:
        """Convert image to a single-page PDF."""
        storage = self.temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="img_")

        # Convert to RGB if necessary (PDF does not support all modes)
        img = self._img
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.save(str(out), "PDF", resolution=100.0)
        return out

    def to_text(self) -> str:
        raise NotImplementedError(
            "Text extraction from images requires OCR, which is not available in v0.0.1."
        )

    def to_images(self, *, format: str = "png") -> list[Path]:
        """Return a copy of the image in the requested format."""
        fmt = format.lower().lstrip(".")
        if fmt not in {"png", "jpg", "jpeg", "webp"}:
            raise ConversionError(f"Unsupported image format: {format}")

        storage = self.temp_storage or TemporaryStorage()
        suffix = f".{fmt if fmt != 'jpeg' else 'jpg'}"
        out = storage.create_file(suffix=suffix, prefix="img_")
        save_fmt = "JPEG" if fmt in ("jpg", "jpeg") else fmt.upper()
        self._img.save(str(out), save_fmt)
        return [out]

    def info(self) -> dict[str, Any]:
        return {
            "filename": self.path.name,
            "type": self.path.suffix.lstrip(".").lower(),
            "size": self.path.stat().st_size,
            "extension": self.path.suffix.lower(),
            "width": self._img.width,
            "height": self._img.height,
            "mode": self._img.mode,
            "format": self._img.format,
        }
