import asyncio

import pytest

from app.model_lifecycle import parse_lifecycle, refresh_public_lifecycle


@pytest.mark.parametrize("badge,status", [("GA", "active"), ("Public Preview", "active"),
                                          ("Deprecated", "deprecated"), ("Retired", "retired")])
def test_official_status_badges(badge, status):
    html = '<nav>Deprecated & retired models</nav><span data-slot="badge">' + badge + '</span>'
    assert parse_lifecycle(html) == status


@pytest.mark.parametrize("html", ["", '<span>GA</span>', '<span data-slot="badge">Unknown</span>',
    '<span data-slot="badge">GA</span><span data-slot="badge">Deprecated</span>'])
def test_missing_changed_or_conflicting_markup_fails_closed(html):
    with pytest.raises(ValueError):
        parse_lifecycle(html)


def test_public_refresh_is_deduplicated_and_historical_status_not_replaced():
    calls = []
    async def fetch(url):
        calls.append(url)
        return '<span data-slot="badge">GA</span>'
    evidence = {
        "alias": dict(source="https://docs.mistral.ai/models/current", refresh_public=True, status="unknown"),
        "version": dict(source="https://docs.mistral.ai/models/current", refresh_public=True, status="unknown"),
        "old": dict(source="https://docs.mistral.ai/models", refresh_public=False, status="deprecated"),
    }
    result = asyncio.run(refresh_public_lifecycle(evidence, fetch))
    assert len(calls) == 1
    assert result["alias"]["status"] == "active"
    assert result["old"]["status"] == "deprecated"
    assert evidence["alias"]["status"] == "unknown"


def test_public_failure_cancels_sibling_requests():
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def fetch(url):
            if url.endswith("slow"):
                entered.set()
                try:
                    await asyncio.sleep(60)
                finally:
                    cancelled.set()
            await entered.wait()
            raise ValueError("no lifecycle evidence")
        evidence = {key: dict(source="https://docs.mistral.ai/models/" + key,
                              refresh_public=True) for key in ["slow", "fail"]}
        with pytest.raises(ExceptionGroup):
            await refresh_public_lifecycle(evidence, fetch)
        assert cancelled.is_set()
    asyncio.run(scenario())
