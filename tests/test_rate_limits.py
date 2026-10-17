from __future__ import annotations

import httpx
import pytest

from edocapi import App


@pytest.mark.asyncio
async def test_global_limit_is_per_client_and_health_is_exempt():
    app = App(dashboard=False).limits(2, per="minute")

    @app.get("/work")
    def work():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.1", 1234)),
        base_url="http://test",
    ) as first_client:
        assert (await first_client.get("/work")).status_code == 200
        second = await first_client.get("/work")
        assert second.status_code == 200
        assert second.headers["x-ratelimit-limit"] == "2"
        assert second.headers["x-ratelimit-remaining"] == "0"
        limited = await first_client.get("/work")
        assert limited.status_code == 429
        assert limited.json()["error"] == "RateLimitExceeded"
        assert int(limited.headers["retry-after"]) > 0

        assert (await first_client.get("/health")).status_code == 200
        assert (await first_client.get("/health")).status_code == 200

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.2", 1234)),
        base_url="http://test",
    ) as other_client:
        assert (await other_client.get("/work")).status_code == 200
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_route_limit_overrides_global_limit():
    app = App(dashboard=False).limits(10, per="minute")
    calls = 0

    @app.post("/convert", limit="1/minute")
    def convert():
        nonlocal calls
        calls += 1
        return {"converted": True}

    @app.get("/status")
    def status():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.3", 1234)),
        base_url="http://test",
    ) as client:
        assert (await client.post("/convert")).status_code == 200
        limited = await client.post("/convert")
        assert limited.status_code == 429
        assert limited.headers["x-ratelimit-limit"] == "1"
        assert (await client.get("/status")).status_code == 200
    assert calls == 1
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_global_limit_remains_upper_bound_for_route_limit():
    app = App(dashboard=False).limits(1, per="minute")

    @app.get("/special", limit="10/minute")
    def special():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.4", 1234)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/special")).status_code == 200
        assert (await client.get("/special")).status_code == 429
    app._temp_storage.cleanup()


@pytest.mark.asyncio
async def test_forwarded_for_header_does_not_change_rate_limit_identity():
    app = App(dashboard=False).limits(1, per="minute")

    @app.get("/work")
    def work():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.5", 1234)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/work", headers={"X-Forwarded-For": "198.51.100.1"})).status_code == 200
        denied = await client.get("/work", headers={"X-Forwarded-For": "198.51.100.2"})
        assert denied.status_code == 429
    app._temp_storage.cleanup()


def test_rate_limit_configuration_rejects_invalid_values():
    app = App(dashboard=False)
    with pytest.raises(ValueError):
        app.limits(0)
    with pytest.raises(ValueError):
        app.limits(10, per="fortnight")
    with pytest.raises(ValueError):
        app.post("/convert", limit="ten/minute")(lambda: None)
    app._temp_storage.cleanup()
