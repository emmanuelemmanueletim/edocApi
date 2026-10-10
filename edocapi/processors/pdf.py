"""PDF processor for eDocAPI (uses pypdf)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from edocapi.exceptions import InvalidDocument, ProcessingError
from edocapi.processors.base import BaseProcessor, register_processor
from edocapi.storage.temporary import TemporaryStorage

logger = logging.getLogger("edocapi.processors.pdf")


@register_processor("pdf")
class PDFProcessor(BaseProcessor):
    """Processor for PDF documents."""

    supported_input_types = {"pdf"}
    supported_output_types = {"pdf", "txt", "html", "png", "jpg", "webp"}

    def __init__(self, path: Path, *, temp_storage: Any = None) -> None:
        super().__init__(path, temp_storage=temp_storage)
        try:
            self._reader = PdfReader(str(path))
        except PdfReadError as exc:
            raise InvalidDocument(f"Invalid or corrupted PDF: {exc}") from exc

    # ------------------------------------------------------------------
    # Basic conversions
    # ------------------------------------------------------------------

    def to_pdf(self) -> Path:
        """Return a copy of the PDF (identity conversion)."""
        out = self._temp_path(suffix=".pdf", prefix="copy_")
        writer = PdfWriter()
        for page in self._reader.pages:
            writer.add_page(page)
        with out.open("wb") as f:
            writer.write(f)
        return out

    def to_text(self) -> str:
        """Extract text from all pages."""
        parts: list[str] = []
        for i, page in enumerate(self._reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"--- Page {i} ---\n{text.strip()}")
        return "\n\n".join(parts)

    def to_html(self) -> str:
        """Simple HTML representation of extracted text."""
        text = self.to_text()
        # Very basic wrapping  not a full visual conversion
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>\n")
        )
        return f"<html><body><pre>{escaped}</pre></body></html>"

    def to_images(self, *, format: str = "png") -> list[Path]:
        """Convert PDF pages to images.

        Requires the optional `pdf2image` package (and poppler).
        If unavailable, raises a clear ProcessingError.
        """
        try:
            from pdf2image import convert_from_path
        except ImportError as exc:
            raise ProcessingError(
                "PDF -> images requires the optional dependency 'pdf2image' "
                "and the system package 'poppler'. "
                "Install with: pip install pdf2image"
            ) from exc

        fmt = format.lower().lstrip(".")
        if fmt not in {"png", "jpg", "jpeg", "webp"}:
            raise ProcessingError(f"Unsupported image format: {format}")

        images = convert_from_path(str(self.path))
        paths: list[Path] = []
        for i, img in enumerate(images, start=1):
            suffix = f".{fmt if fmt != 'jpeg' else 'jpg'}"
            out = self._temp_path(suffix=suffix, prefix=f"page_{i}_")
            img.save(str(out), fmt.upper() if fmt != "jpg" else "JPEG")
            paths.append(out)
        return paths

    def info(self) -> dict[str, Any]:
        meta = self._reader.metadata or {}
        return {
            "filename": self.path.name,
            "type": "pdf",
            "pages": len(self._reader.pages),
            "size": self.path.stat().st_size,
            "extension": ".pdf",
            "title": getattr(meta, "title", None) or meta.get("/Title"),
            "author": getattr(meta, "author", None) or meta.get("/Author"),
            "subject": getattr(meta, "subject", None) or meta.get("/Subject"),
            "creator": getattr(meta, "creator", None) or meta.get("/Creator"),
            "producer": getattr(meta, "producer", None) or meta.get("/Producer"),
            "creation_date": str(getattr(meta, "creation_date", None) or meta.get("/CreationDate") or ""),
            "modification_date": str(getattr(meta, "modification_date", None) or meta.get("/ModDate") or ""),
        }

    # ------------------------------------------------------------------
    # PDF operations
    # ------------------------------------------------------------------

    def compress(self, level: str = "medium", target_size: int | None = None) -> Path:
        """Compress the PDF.

        Levels:
            low     minimal compression (mostly remove unused objects)
            medium  default, moderate image quality reduction if possible
            high    aggressive (may reduce quality)

        Note: pypdf's compression is limited; this is a best-effort implementation.
        """
        level = level.lower()
        if level not in {"low", "medium", "high"}:
            raise ProcessingError(f"Unknown compression level: {level}")

        writer = PdfWriter()
        for page in self._reader.pages:
            writer.add_page(page)
            # Work on the writer-owned copy; add_page may clone the reader page.
            writer.pages[-1].compress_content_streams()

        # Remove unused objects / metadata for higher levels
        if level in {"medium", "high"}:
            try:
                writer.compress_identical_objects(
                    remove_duplicates=True, remove_unreferenced=True
                )
            except TypeError:
                # older pypdf API
                writer.compress_identical_objects(
                    remove_identicals=True, remove_orphans=True
                )

        if target_size is not None:
            return self._compress_to_target(target_size, level)

        out = self._temp_path(suffix=".pdf", prefix="compressed_")
        with out.open("wb") as f:
            writer.write(f)
        if out.stat().st_size >= self.path.stat().st_size:
            out.unlink(missing_ok=True)
            return self.path
        return out

    def _compress_to_target(self, target_size: int, level: str) -> Path:
        """Use Ghostscript image downsampling and verify the actual output size."""
        if target_size <= 0:
            raise ProcessingError("Target size must be greater than zero bytes.")
        if self.path.stat().st_size <= target_size:
            return self.path
        executable = shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")
        if not executable:
            return self._compress_images_to_target(target_size, level)

        settings = {
            "low": ("/printer", 300),
            "medium": ("/ebook", 150),
            "high": ("/screen", 96),
        }
        preset, initial_dpi = settings[level]
        attempts = []
        for dpi in (initial_dpi, 120, 96, 72, 50, 36):
            if dpi not in attempts:
                attempts.append(dpi)
        best_path: Path | None = None
        best_size: int | None = None
        for dpi in attempts:
            out = self._temp_path(suffix=".pdf", prefix="compressed_")
            command = [
                executable,
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={preset}",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                "-dDownsampleColorImages=true",
                "-dDownsampleGrayImages=true",
                "-dDownsampleMonoImages=true",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
                f"-dColorImageResolution={dpi}",
                f"-dGrayImageResolution={dpi}",
                "-dMonoImageResolution=300",
                f"-sOutputFile={out}",
                str(self.path),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0 or not out.exists():
                out.unlink(missing_ok=True)
                detail = (result.stderr or result.stdout or "").strip()
                raise ProcessingError(f"Ghostscript PDF compression failed: {detail[-1000:]}")
            size = out.stat().st_size
            if best_size is None or size < best_size:
                if best_path is not None:
                    best_path.unlink(missing_ok=True)
                best_path, best_size = out, size
            else:
                out.unlink(missing_ok=True)
            if size <= target_size:
                return out

        if best_path is not None and best_size is not None:
            if best_size < self.path.stat().st_size:
                return best_path
            best_path.unlink(missing_ok=True)
            return self.path
        raise ProcessingError("Ghostscript did not produce a compressed PDF.")

    def _compress_images_to_target(self, target_size: int, level: str) -> Path:
        """Re-encode embedded raster images with Pillow until target is met."""
        from PIL import Image
        from pypdf.generic import ContentStream, DecodedStreamObject, NameObject, NumberObject

        # Each pass starts from the original reader pages, so quality reductions
        # do not accumulate and every candidate can be compared fairly.
        settings = {
            "low": [(88, 1.0), (78, 0.85), (68, 0.7), (58, 0.55), (48, 0.4), (38, 0.3)],
            "medium": [(78, 0.85), (68, 0.7), (58, 0.55), (48, 0.4), (38, 0.3), (28, 0.2)],
            "high": [(62, 0.65), (52, 0.5), (42, 0.4), (32, 0.3), (24, 0.22), (16, 0.15)],
        }
        best_path: Path | None = None
        best_size: int | None = None
        images_changed = False

        def optimize_resources(resources, writer: PdfWriter, quality: int, scale: float) -> int:
            changed = 0
            xobjects = resources.get("/XObject")
            if not xobjects:
                return changed
            xobjects = xobjects.get_object()
            for name, ref in list(xobjects.items()):
                obj = ref.get_object()
                subtype = obj.get("/Subtype")
                if subtype == "/Image":
                    if obj.get("/ImageMask") or obj.get("/Mask"):
                        continue
                    try:
                        original = Image.open(BytesIO(obj.get_data()))
                        original.load()
                    except Exception:
                        continue
                    if original.width < 2 or original.height < 2:
                        continue
                    width = max(1, int(original.width * scale))
                    height = max(1, int(original.height * scale))
                    if original.mode not in ("RGB", "L"):
                        rgba = original.convert("RGBA")
                        background = Image.new("RGB", rgba.size, "white")
                        background.paste(rgba, mask=rgba.getchannel("A"))
                        image = background
                    else:
                        image = original.convert("RGB") if original.mode != "L" else original
                    if image.size != (width, height):
                        image = image.resize((width, height), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=quality, optimize=True)
                    optimized = DecodedStreamObject()
                    for key, value in obj.items():
                        if str(key) not in {
                            "/Filter", "/DecodeParms", "/ColorSpace",
                            "/BitsPerComponent", "/Width", "/Height",
                            "/Mask",
                        }:
                            optimized[key] = value
                    optimized.set_data(output.getvalue())
                    optimized[NameObject("/Filter")] = NameObject("/DCTDecode")
                    optimized[NameObject("/ColorSpace")] = NameObject(
                        "/DeviceGray" if image.mode == "L" else "/DeviceRGB"
                    )
                    optimized[NameObject("/BitsPerComponent")] = NumberObject(8)
                    optimized[NameObject("/Width")] = NumberObject(width)
                    optimized[NameObject("/Height")] = NumberObject(height)
                    xobjects[name] = writer._add_object(optimized)
                    changed += 1
                elif subtype == "/Form":
                    nested = obj.get("/Resources")
                    if nested:
                        changed += optimize_resources(nested.get_object(), writer, quality, scale)
            return changed

        def optimize_inline_images(page, quality: int, scale: float) -> int:
            content = page.get_contents()
            if content is None:
                return 0
            stream = ContentStream(content, page.pdf)
            changed = 0
            operations = []
            for operands, operator in stream.operations:
                if operator == b"INLINE IMAGE":
                    settings_dict = operands["settings"]
                    image_data = operands["data"]
                    filter_type = settings_dict.get("/F", settings_dict.get("/Filter"))
                    try:
                        if filter_type in ("/DCT", "/DCTDecode"):
                            image = Image.open(BytesIO(image_data))
                        elif filter_type is None:
                            width = int(settings_dict.get("/W", settings_dict.get("/Width", 0)))
                            height = int(settings_dict.get("/H", settings_dict.get("/Height", 0)))
                            color = settings_dict.get("/CS", settings_dict.get("/ColorSpace"))
                            bits = int(settings_dict.get("/BPC", settings_dict.get("/BitsPerComponent", 8)))
                            mode = {"/RGB": "RGB", "/DeviceRGB": "RGB", "/G": "L", "/DeviceGray": "L"}.get(str(color))
                            if not mode or bits != 8 or width < 1 or height < 1:
                                operations.append((operands, operator))
                                continue
                            image = Image.frombytes(mode, (width, height), image_data)
                        else:
                            operations.append((operands, operator))
                            continue
                        image.load()
                    except Exception:
                        operations.append((operands, operator))
                        continue
                    width = max(1, int(image.width * scale))
                    height = max(1, int(image.height * scale))
                    if image.mode not in ("RGB", "L"):
                        rgba = image.convert("RGBA")
                        background = Image.new("RGB", rgba.size, "white")
                        background.paste(rgba, mask=rgba.getchannel("A"))
                        image = background
                    elif image.mode != "L":
                        image = image.convert("RGB")
                    if image.size != (width, height):
                        image = image.resize((width, height), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=quality, optimize=True)
                    for key in ("/F", "/Filter", "/DP", "/DecodeParms", "/CS", "/ColorSpace", "/BPC", "/BitsPerComponent", "/W", "/Width", "/H", "/Height"):
                        settings_dict.pop(NameObject(key), None)
                    settings_dict[NameObject("/W")] = NumberObject(width)
                    settings_dict[NameObject("/H")] = NumberObject(height)
                    settings_dict[NameObject("/CS")] = NameObject("/G" if image.mode == "L" else "/RGB")
                    settings_dict[NameObject("/BPC")] = NumberObject(8)
                    settings_dict[NameObject("/F")] = NameObject("/DCT")
                    operands["data"] = output.getvalue()
                    changed += 1
                operations.append((operands, operator))
            if changed:
                stream.operations = operations
                page.replace_contents(stream)
            return changed

        for quality, scale in settings[level]:
            writer = PdfWriter()
            changed = 0
            for page in self._reader.pages:
                writer.add_page(page)
                page_copy = writer.pages[-1]
                resources = page_copy.get("/Resources")
                if resources:
                    changed += optimize_resources(resources.get_object(), writer, quality, scale)
                changed += optimize_inline_images(page_copy, quality, scale)
                page_copy.compress_content_streams()
            if level in {"medium", "high"}:
                writer.compress_identical_objects(
                    remove_duplicates=True, remove_unreferenced=True
                )
            out = self._temp_path(suffix=".pdf", prefix="compressed_")
            with out.open("wb") as stream:
                writer.write(stream)
            size = out.stat().st_size
            images_changed = images_changed or changed > 0
            if best_size is None or size < best_size:
                if best_path is not None:
                    best_path.unlink(missing_ok=True)
                best_path, best_size = out, size
            else:
                out.unlink(missing_ok=True)
            if size <= target_size:
                if best_path != out and best_path is not None:
                    best_path.unlink(missing_ok=True)
                return out

        if best_path is None or best_size is None:
            raise ProcessingError("PDF image optimization did not produce an output.")
        if best_size >= self.path.stat().st_size:
            best_path.unlink(missing_ok=True)
            return self._compress_text_to_target(target_size) or self.path
        if not images_changed:
            if best_size > target_size:
                text_pdf = self._compress_text_to_target(target_size)
                if text_pdf is not None:
                    best_path.unlink(missing_ok=True)
                    return text_pdf
            return best_path
        # Return the smallest valid candidate even when the requested target
        # cannot be met; the UI compares its actual size with the target.
        return best_path

    def _compress_text_to_target(self, target_size: int) -> Path | None:
        """Rebuild text PDFs with standard fonts when lossless optimization misses target."""
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        pages_text = [(page.extract_text() or "").strip() for page in self._reader.pages]
        if not any(pages_text) or sum(map(len, pages_text)) < 100:
            return None

        writer = PdfWriter()
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
        font_ref = writer._add_object(font)
        for original_page, page_text in zip(self._reader.pages, pages_text):
            lines: list[str] = []
            for paragraph in page_text.splitlines():
                lines.extend(textwrap.wrap(paragraph, width=100) or [""])
            if not lines:
                lines = [""]
            for offset in range(0, len(lines), 60):
                page = writer.add_blank_page(
                    width=float(original_page.mediabox.width),
                    height=float(original_page.mediabox.height),
                )
                page[NameObject("/Resources")] = DictionaryObject(
                    {
                        NameObject("/Font"): DictionaryObject(
                            {NameObject("/F1"): font_ref}
                        )
                    }
                )
                commands = ["BT /F1 9 Tf 42 800 Td 12 TL"]
                for line in lines[offset : offset + 60]:
                    safe = (
                        line.encode("cp1252", "replace")
                        .decode("cp1252")
                        .replace("\\", "\\\\")
                        .replace("(", "\\(")
                        .replace(")", "\\)")
                    )
                    commands.append(f"({safe}) Tj T*")
                commands.append("ET")
                stream = DecodedStreamObject()
                stream.set_data("\n".join(commands).encode("cp1252"))
                page[NameObject("/Contents")] = writer._add_object(stream)

        output = self._temp_path(suffix=".pdf", prefix="compressed_text_")
        with output.open("wb") as destination:
            writer.write(destination)
        if output.stat().st_size <= target_size:
            self._last_compression_mode = "text-reflow"
            return output
        output.unlink(missing_ok=True)
        return None

    def split(self) -> list[Path]:
        """Split into one PDF per page."""
        paths: list[Path] = []
        for i, page in enumerate(self._reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            out = self._temp_path(suffix=".pdf", prefix=f"page_{i}_")
            with out.open("wb") as f:
                writer.write(f)
            paths.append(out)
        return paths

    def extract_pages(self, start: int, end: int | None = None) -> Path:
        """Extract pages start..end (1-based inclusive)."""
        total = len(self._reader.pages)
        if start < 1 or start > total:
            raise ProcessingError(f"Start page {start} out of range (1-{total}).")
        if end is None:
            end = total
        if end < start or end > total:
            raise ProcessingError(f"End page {end} out of range ({start}-{total}).")

        writer = PdfWriter()
        for i in range(start - 1, end):  # convert to 0-based
            writer.add_page(self._reader.pages[i])

        out = self._temp_path(
            suffix=".pdf",
            prefix=f"pages_{start}-{end}_",
        )
        with out.open("wb") as f:
            writer.write(f)
        return out

    def rotate(self, degrees: int = 90, pages: Sequence[int] | None = None) -> Path:
        """Rotate pages by degrees (90, 180, 270). pages is 1-based."""
        if degrees % 90 != 0:
            raise ProcessingError("Rotation must be a multiple of 90 degrees.")

        writer = PdfWriter()
        total = len(self._reader.pages)
        page_set = set(pages) if pages else None

        for i, page in enumerate(self._reader.pages, start=1):
            if page_set is None or i in page_set:
                page.rotate(degrees)
            writer.add_page(page)

        out = self._temp_path(suffix=".pdf", prefix="rotated_")
        with out.open("wb") as f:
            writer.write(f)
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _temp_path(self, suffix: str = "", prefix: str = "pdf_") -> Path:
        storage = self.temp_storage or TemporaryStorage()
        return storage.create_file(suffix=suffix, prefix=prefix)

    @staticmethod
    def merge(paths: Sequence[Path], *, temp_storage: TemporaryStorage | None = None) -> Path:
        """Merge multiple PDFs into one."""
        writer = PdfWriter()
        for p in paths:
            try:
                reader = PdfReader(str(p))
                for page in reader.pages:
                    writer.add_page(page)
            except PdfReadError as exc:
                raise InvalidDocument(f"Cannot read PDF for merge: {p.name}: {exc}") from exc

        storage = temp_storage or TemporaryStorage()
        out = storage.create_file(suffix=".pdf", prefix="merged_")
        with out.open("wb") as f:
            writer.write(f)
        return out
