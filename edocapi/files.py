"""File upload helpers for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from starlette.datastructures import UploadFile
from starlette.requests import Request

from edocapi.exceptions import FileTooLarge, ValidationError
from edocapi.storage.temporary import TemporaryStorage
from edocapi.validation.files import detect_type_from_bytes, validate_extension

logger = logging.getLogger("edocapi.files")


async def extract_uploads(
    request: Request,
    *,
    max_size: int,
    max_files: int = 20,
    temp_storage: TemporaryStorage | None = None,
) -> list[Path]:
    """Extract and validate uploaded files from a multipart request.

    Returns a list of paths to temporary files that contain the uploaded content.
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise ValidationError(
            "Expected multipart/form-data for file uploads. "
            "Did you forget to set enctype='multipart/form-data'?"
        )

    form = await request.form()
    uploads: list[Path] = []

    # Collect all UploadFile instances (single 'file' or multiple 'files')
    candidates: list[UploadFile] = []
    for key in form:
        value = form.getlist(key)
        for item in value:
            if isinstance(item, UploadFile):
                candidates.append(item)

    if not candidates:
        raise ValidationError("No file part found in the request.")

    if len(candidates) > max_files:
        raise ValidationError(
            f"Too many files uploaded ({len(candidates)}). Maximum is {max_files}."
        )

    storage = temp_storage or TemporaryStorage()

    for upload in candidates:
        filename = upload.filename or "unnamed"
        path: Path | None = None
        try:
            safe_name = validate_extension(filename)
            detected = bytearray()
            path = storage.create_file(suffix=Path(safe_name).suffix, prefix="upload_")
            size = 0
            with path.open("wb") as destination:
                while chunk := await upload.read(min(64 * 1024, max_size - size + 1)):
                    size += len(chunk)
                    if size > max_size:
                        raise FileTooLarge(size=size, max_size=max_size)
                    destination.write(chunk)
                    if len(detected) < 4096:
                        detected.extend(chunk[:4096 - len(detected)])

            kind = detect_type_from_bytes(bytes(detected))
            if kind is None and Path(safe_name).suffix.lower() not in {
                ".txt", ".md", ".markdown", ".html", ".htm"
            }:
                raise ValidationError("Unable to determine a supported file type from content.")

            uploads.append(path)
            logger.info("Document uploaded: %s (%d bytes)", safe_name, size)
        except Exception:
            # A rejected or partially written upload must not remain on disk.
            if path is not None:
                storage.discard(path)
            raise
        finally:
            await upload.close()

    return uploads
