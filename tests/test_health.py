import asyncio

import httpx

from app.main import app, healthz


def test_healthz_is_content_free() -> None:
    assert asyncio.run(healthz()) == {
        "service": "caption-bridge",
        "status": "ok",
    }


def test_favicon_request_is_handled_without_external_asset() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://loopback.test"
        ) as client:
            return await client.get("/favicon.ico")

    response = asyncio.run(request())
    assert response.status_code == 204
    assert response.content == b""
