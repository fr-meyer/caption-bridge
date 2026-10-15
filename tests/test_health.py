import asyncio

import httpx

from app.identity import PACKAGE_VERSION
from app.main import app, healthz, version


def test_healthz_is_content_free() -> None:
    assert asyncio.run(healthz()) == {
        "service": "caption-bridge",
        "status": "ok",
    }


def test_version_is_content_free() -> None:
    payload = asyncio.run(version())
    assert payload["service"] == "caption-bridge"
    assert payload["package_version"] == PACKAGE_VERSION
    assert "MISTRAL" not in str(payload)
    assert "/Users/" not in str(payload)


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


def test_browser_assets_are_not_cached() -> None:
    async def request(path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://loopback.test"
        ) as client:
            return await client.get(path)

    for path in ("/", "/app.js", "/pcm-player.js", "/audio-devices.js", "/styles.css"):
        response = asyncio.run(request(path))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"



def test_version_route_offloads_blocking_identity() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "await asyncio.to_thread(runtime_identity)" in source
