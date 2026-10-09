"""File upload helpers for eDocAPI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from starlette.datastructures import UploadFile
from starlette.requests import Request

from edocapi.exceptions import ValidationError
from edocapi.storage.temporary import TemporaryStorage, safe_filename
from edocapi.validation.files import validate_upload

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
        # Read content
        content = await upload.read()
        await upload.close()

        safe_name, data = validate_upload(
            filename,
            content,
            max_size=max_size,
        )

        # Write to temporary storage
        suffix = Path(safe_name).suffix
        path = storage.create_file(suffix=suffix, prefix="upload_", content=data)
        # Preserve original safe name for later use
        path = path.with_name(safe_name)
        # Re-write under the desired name if needed
        if not path.exists():
            path.write_bytes(data)
            storage.register(path)

        uploads.append(path)
        logger.info("Document uploaded: %s (%d bytes)", safe_name, len(data))

    return uploads
