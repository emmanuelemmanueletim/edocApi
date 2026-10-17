"""Size-limited streaming multipart parser for eDocAPI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
    body: bytes | Any,
    content_type: str,
    *,
    max_size: int,
    max_files: int,
    temp_storage: TemporaryStorage,
    max_request_size: int | None = None,
    content_length: int | None = None,
) -> tuple[list[Path], dict[str, str]]:
    """Parse a byte string or async request stream without buffering file bodies."""
    boundary = _parse_boundary(content_type)
    if not boundary:
        raise ValidationError("Missing or invalid multipart boundary.")
    total_limit = max_request_size if max_request_size is not None else max_size * max_files
    if content_length is not None and content_length > total_limit:
        raise FileTooLarge("Request body exceeds the configured limit.", size=content_length, limit=total_limit)
    files: list[Path] = []
    fields: dict[str, str] = {}
    total = 0
    file_count = 0
    current_file = None
    current_path: Path | None = None
    current_field = bytearray()
    current_size = 0
    current_name = ""
    header_name = bytearray()
    header_value = bytearray()
    headers: dict[str, bytes] = {}
    final_boundary_marker = b"--" + boundary.encode("latin-1") + b"--"
    ending_tail = bytearray()
    stream_final_boundary_seen = False

    def on_part_begin() -> None:
        nonlocal current_file, current_path, current_field, current_size, current_name, headers
        current_file = current_path = None
        current_field = bytearray()
        current_size = 0
        current_name = ""
        headers = {}

    def on_header_field(data: bytes, start: int, end: int) -> None:
        header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        header_value.extend(data[start:end])

    def on_header_end() -> None:
        nonlocal header_name, header_value
        headers[bytes(header_name).decode("latin-1").lower()] = bytes(header_value)
        header_name = bytearray()
        header_value = bytearray()

    def on_headers_finished() -> None:
        nonlocal current_name, current_file, current_path, file_count
        disposition = headers.get("content-disposition", b"").decode("latin-1", errors="replace")
        name_match = re.search(r'(?:^|;)\s*name="([^"]*)"', disposition, re.IGNORECASE)
        filename_match = re.search(r'(?:^|;)\s*filename="([^"]*)"', disposition, re.IGNORECASE)
        current_name = name_match.group(1) if name_match else ""
        if filename_match is not None and not filename_match.group(1):
            current_name = ""
            return
        if not current_name or len(current_name) > 200:
            raise ValidationError("Invalid or overlong multipart field name.")
        if filename_match is not None and filename_match.group(1):
            file_count += 1
            if file_count > max_files:
                raise ValidationError(f"Too many files (max {max_files}).")
            filename = safe_filename(filename_match.group(1))
            if ".." in filename or "/" in filename or "\\" in filename:
                raise SecurityError("Invalid filename detected.")
            current_path = temp_storage.create_file(suffix=Path(filename).suffix, prefix="upload_")
            current_file = current_path.open("wb")

    def on_part_data(data: bytes, start: int, end: int) -> None:
        nonlocal current_size
        chunk = data[start:end]
        current_size += len(chunk)
        limit = max_size if current_file is not None else _MAX_FIELD_BYTES
        if current_size > limit:
            raise FileTooLarge("Multipart part exceeds its size limit.", size=current_size, limit=limit)
        if current_file is not None:
            current_file.write(chunk)
        else:
            current_field.extend(chunk)

    def on_part_end() -> None:
        nonlocal current_file, current_path
        if current_file is not None:
            current_file.close()
            files.append(current_path)
            current_file = current_path = None
        else:
            if len(fields) >= _MAX_FIELDS and current_name not in fields:
                raise ValidationError(f"Too many form fields (max {_MAX_FIELDS}).")
            fields[current_name] = bytes(current_field).decode("utf-8", errors="replace")

    def on_end() -> None:
        return None

    try:
        from multipart.multipart import MultipartParser
    except ImportError:
        from python_multipart import MultipartParser

    parser = MultipartParser(
        boundary.encode("latin-1"),
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
            "on_end": on_end,
        },
    )
    parser.max_size = total_limit

    if isinstance(body, bytes):
        async def one_chunk():
            yield body
        body = one_chunk()

    try:
        async for chunk in body:
            total += len(chunk)
            if total > total_limit:
                raise FileTooLarge("Request body exceeds the configured limit.", size=total, limit=total_limit)
            parser.write(chunk)
            ending_tail.extend(chunk)
            if len(ending_tail) > len(final_boundary_marker) + 4:
                del ending_tail[:-len(final_boundary_marker) - 4]
            if final_boundary_marker in ending_tail:
                stream_final_boundary_seen = True
        parser.finalize()
        if not stream_final_boundary_seen:
            raise ValidationError("Incomplete multipart body.")
        return files, fields
    except Exception:
        if current_file is not None:
            current_file.close()
        for path in files + ([current_path] if current_path else []):
            temp_storage.discard(path)
        raise


def _parse_pure(
    body: bytes,
    content_type: str,
    *,
    max_size: int,
    max_files: int,
    temp_storage: TemporaryStorage,
) -> tuple[list[Path], dict[str, str]]:
    """Synchronous compatibility wrapper around the streaming parser."""
    import asyncio

    async def run():
        async def one_chunk():
            yield body
        return await parse_multipart(
            one_chunk(), content_type, max_size=max_size,
            max_files=max_files, temp_storage=temp_storage,
        )

    return asyncio.run(run())
