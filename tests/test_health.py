import asyncio

from app.main import healthz


def test_healthz_is_content_free() -> None:
    assert asyncio.run(healthz()) == {
        "service": "caption-bridge",
        "status": "ok",
    }
