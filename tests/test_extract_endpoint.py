from pathlib import Path

import httpx
import pytest

from edocapi import App, Document
from edocapi.config import MAX_FILE_SIZE_BYTES
from edocapi.responses import JSONResponse
from edocapi.exceptions import ValidationError
from edocapi.http.multipart import _parse_pure
from edocapi.storage.temporary import TemporaryStorage


def test_app_upload_limit_defaults_to_50mb_and_accepts_smaller_values():
    assert App(dashboard=False).config.max_file_size == MAX_FILE_SIZE_BYTES
    assert App(max_file_size="10MB", dashboard=False).config.max_file_size == 10 * 1024 * 1024
    with pytest.raises(ValueError, match="cannot exceed"):
        App(max_file_size="51MB", dashboard=False)


def test_json_response_preserves_unicode_for_all_clients():
    response = JSONResponse({"text": "𝑣 = √𝑥 — Ω"})
    body = response.body()
    assert body.isascii()
    assert body.decode("ascii") == '{"text": "\\ud835\\udc63 = \\u221a\\ud835\\udc65 \\u2014 \\u03a9"}'


@pytest.mark.asyncio
async def test_extract_endpoint_returns_text_and_cleans_uploaded_file(tmp_path):
    app = App(temp_dir=str(tmp_path), dashboard=False)

    @app.post("/extract")
    def extract(file):
        return {"text": Document(file).extract_text()}

    fixture = Path(__file__).parent / "fixtures" / "edge_ai_research_report.pdf"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/extract",
            files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["text"].startswith("# ARTIFICIAL INTELLIGENCE AT THE EDGE:")
    assert not app._temp_storage._files
    app._temp_storage.cleanup()


def test_multipart_parser_cleans_partial_uploads_on_rejection(tmp_path):
    storage = TemporaryStorage(tmp_path)
    boundary = "boundary"
    body = (
        b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"one.pdf\"\r\n"
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n"
        b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"two.pdf\"\r\n"
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n--boundary--\r\n"
    )

    with pytest.raises(ValidationError):
        _parse_pure(body, f"multipart/form-data; boundary={boundary}",
                    max_size=1024, max_files=1, temp_storage=storage)

    assert not storage._files
    storage.cleanup()
