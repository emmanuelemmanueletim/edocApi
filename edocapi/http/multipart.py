"""Size-limited multipart/form-data parser for eDocAPI."""

from __future__ import annotations

import re
from pathlib import Path

from edocapi.exceptions import FileTooLarge, SecurityError, ValidationError
from edocapi.storage.temporary import TemporaryStorage, safe_filename

_MAX_FIELDS = 100
_MAX_FIELD_BYTES = 64 * 1024


def _parse_boundary(content_type: str) -> str | None:
    match = re.search(r'(?:^|;)\s*boundary=(?:"([^"]+)"|([^;\s]+))', content_type, re.IGNORECASE)
    if not match:
        return None
    boundary = match.group(1) or match.group(2)
    if not boundary or len(boundary) > 70 or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=?-]+", boundary):
        return None
    return boundary


async def parse_multipart(
    body: bytes,
    content_type: str,
    *,
    max_size: int,
    max_files: int,
    temp_storage: TemporaryStorage,
) -> tuple[list[Path], dict[str, str]]:
    """Parse multipart body.

    Returns (list_of_uploaded_file_paths, form_fields_dict).
    """
    if len(body) > max_size * max_files:  # rough overall limit
        raise FileTooLarge(
            f"Request body too large ({len(body)} bytes).",
            size=len(body),
            limit=max_size * max_files,
        )

    return _parse_pure(body, content_type, max_size=max_size, max_files=max_files, temp_storage=temp_storage)


def _parse_pure(
    body: bytes,
    content_type: str,
    *,
    max_size: int,
    max_files: int,
    temp_storage: TemporaryStorage,
) -> tuple[list[Path], dict[str, str]]:
    """Pure-Python multipart parser (secure, size-aware)."""
    boundary = _parse_boundary(content_type)
    if not boundary:
        raise ValidationError("Missing or invalid multipart boundary.")

    delim = b"--" + boundary.encode("latin-1")
    parts = body.split(delim)
    files: list[Path] = []
    fields: dict[str, str] = {}
    file_count = 0

    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--" or part == b"-":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, data = part.split(b"\r\n\r\n", 1)
        # Remove trailing boundary markers
        if data.endswith(b"--"):
            data = data[:-2]
        data = data.rstrip(b"\r\n")

        headers = header_blob.decode("latin-1", errors="replace")
        name_match = re.search(r'name="([^"]+)"', headers, re.IGNORECASE)
        filename_match = re.search(r'filename="([^"]*)"', headers, re.IGNORECASE)

        if not name_match:
            continue
        name = name_match.group(1)

        if filename_match is not None:
            filename = filename_match.group(1)
            if not filename:
                continue  # empty file field
            file_count += 1
            if file_count > max_files:
                raise ValidationError(f"Too many files (max {max_files}).")
            if len(data) > max_size:
                raise FileTooLarge(
                    f"Uploaded file exceeds size limit of {max_size} bytes.",
                    size=len(data),
                    limit=max_size,
                )
            safe = safe_filename(filename)
            # Reject path traversal attempts that survived safe_filename
            if ".." in safe or "/" in safe or "\\" in safe:
                raise SecurityError("Invalid filename detected.")
            path = temp_storage.create_file(
                suffix=Path(safe).suffix,
                prefix="upload_",
                content=data,
            )
            files.append(path)
        else:
            if len(fields) >= _MAX_FIELDS and name not in fields:
                raise ValidationError(f"Too many form fields (max {_MAX_FIELDS}).")
            if len(data) > _MAX_FIELD_BYTES:
                raise FileTooLarge("Form field exceeds the size limit.", size=len(data), limit=_MAX_FIELD_BYTES)
            if len(name) > 200:
                raise ValidationError("Form field name is too long.")
            try:
                fields[name] = data.decode("utf-8", errors="replace")
            except Exception:
                fields[name] = ""

    return files, fields
