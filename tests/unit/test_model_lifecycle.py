import asyncio
import copy
import json
from pathlib import Path

import pytest

from app.model_lifecycle import (
    _FlightScripts,
    _nodes,
    parse_lifecycle,
    refresh_public_lifecycle,
    verify_current_card,
)


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
        return FIXTURE.read_text()
    evidence = {
        "mistral-large-latest": dict(source=URL, refresh_public=True, status="unknown"),
        "mistral-large-4": dict(source=URL, refresh_public=True, status="unknown"),
        "old": dict(source="https://docs.mistral.ai/models", refresh_public=False, status="deprecated"),
    }
    result = asyncio.run(refresh_public_lifecycle(evidence, fetch))
    assert len(calls) == 1
    assert result["mistral-large-latest"]["status"] == "active"
    assert result["old"]["status"] == "deprecated"
    assert evidence["mistral-large-latest"]["status"] == "unknown"


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


def test_changed_identity_cannot_renew_active_badge():
    async def fetch(url):
        return '<span data-slot="badge">GA</span><script>{"names":["replacement"]}</script>'
    with pytest.raises(ExceptionGroup):
        asyncio.run(refresh_public_lifecycle({"original": dict(
            source="https://docs.mistral.ai/models/current", refresh_public=True)}, fetch))


FIXTURE = Path(__file__).parents[1] / "fixtures/model-lifecycle/large-current-flight.html"
URL = "https://docs.mistral.ai/models/mistral-large-4-0"
EXPECTED = {"mistral-large-4", "mistral-large-latest"}


def flight_records():
    parser = _FlightScripts()
    parser.feed(FIXTURE.read_text())
    return {key: json.loads(body) for line in "".join(parser.chunks).splitlines()
            for key, _, body in [line.partition(":")]}


def encode(records):
    stream = "".join(key + ":" + json.dumps(value) + "\n" for key, value in records.items())
    return "<script>self.__next_f.push(" + json.dumps([1, stream]) + ")</script>"


def current_header(records):
    return next(node for node in _nodes(records["e"])
                if "gap-6" in node[3].get("className", ""))


@pytest.mark.parametrize("status,expected", [("GA", "active"), ("Deprecated", "deprecated"),
                                            ("Public Preview", "active"), ("Retired", "retired")])
def test_actual_current_card_lifecycle_scope(status, expected):
    records = flight_records()
    header = current_header(records)
    badge = next(node for node in _nodes(header) if node[3].get("data-slot") == "badge")
    badge[3]["children"] = status
    # An unrelated rendered badge and history record must not affect this card.
    records["fff"] = {"names": ["unrelated"], "status": "Retired"}
    html = '<span data-slot="badge">Retired</span>' + encode(records)
    assert verify_current_card(URL, html, EXPECTED) == expected


@pytest.mark.parametrize("location", ["history", "navigation", "header-navigation", "other-card", "split"])
def test_incidental_or_disjoint_aliases_cannot_renew(location):
    records = flight_records()
    header = current_header(records)
    declaration = next(node for node in _nodes(header) if "names" in node[3])
    old = copy.deepcopy(declaration)
    declaration[3]["names"] = ["replacement"]
    if location == "split":
        declaration[3]["names"] = ["mistral-large-4"]
        old[3]["names"] = ["mistral-large-latest"]
        header[3]["children"].append(old)
    elif location == "header-navigation":
        row = header[3]["children"][-1]
        row[3]["children"][1] = ["$", "nav", None, {"children": old}]
    elif location == "other-card":
        other = copy.deepcopy(header)
        next(node for node in _nodes(other) if "names" in node[3])[3]["names"] = list(EXPECTED)
        records["e"][3]["children"].append(other)
    else:
        records["fff"] = {location: old}
    with pytest.raises(ValueError):
        verify_current_card(URL, encode(records), EXPECTED)


@pytest.mark.parametrize("mutation", ["wrong-source", "conflicting-status", "conflicting-card",
                                      "missing-header", "unscoped", "wrong-segment", "malformed"])
def test_missing_ambiguous_or_malformed_card_fails_closed(mutation):
    records = flight_records()
    header = current_header(records)
    if mutation == "wrong-source":
        records["0"]["c"][-1] = "replacement"
    elif mutation == "conflicting-status":
        header[3]["children"].append(["$", "span", None,
            {"data-slot": "badge", "children": "Deprecated"}])
    elif mutation == "conflicting-card":
        records["e"][3]["children"].append(copy.deepcopy(header))
    elif mutation == "missing-header":
        header[3]["className"] = "unrecognized"
    elif mutation == "wrong-segment":
        for value in records.values():
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], dict):
                        segment = entry[1].get("s")
                        if isinstance(segment, dict) and segment.get("n") == "slug":
                            segment["k"] = "replacement"
    elif mutation == "unscoped":
        records["0"]["t"]["t"].pop("c")
    html = encode(records)
    if mutation == "malformed":
        html = html.replace('self.__next_f.push([1,', 'self.__next_f.push([1,invalid', 1)
    with pytest.raises((ValueError, KeyError)):
        verify_current_card(URL, html, EXPECTED)


@pytest.mark.parametrize("fixture,slug,names,status", [
    ("deprecated-current-flight", "magistral-small-1-2-25-09",
     {"magistral-small-2509", "magistral-small-latest"}, "deprecated"),
    ("lazy-current-flight", "deepseek-v4-flash-1017", {"deepseek-v4-1-flash-1017"}, "active"),
])
def test_actual_deprecated_and_lazy_name_cards(fixture, slug, names, status):
    html = FIXTURE.with_name(fixture + ".html").read_text()
    assert verify_current_card("https://docs.mistral.ai/models/" + slug, html, names) == status


def test_missing_lazy_name_record_is_not_replaced_by_incidental_names():
    parser = _FlightScripts()
    parser.feed(FIXTURE.with_name("lazy-current-flight.html").read_text())
    records = {key: json.loads(body) for line in "".join(parser.chunks).splitlines()
               for key, _, body in [line.partition(":")]}
    key = next(key for key, value in records.items()
               if any("names" in node[3] for node in _nodes(value)) and key != "e")
    del records[key]
    records["fff"] = {"names": ["deepseek-v4-1-flash-1017"]}
    with pytest.raises(ValueError):
        verify_current_card("https://docs.mistral.ai/models/deepseek-v4-flash-1017",
                            encode(records), {"deepseek-v4-1-flash-1017"})


def test_invalid_json_escape_in_real_flight_envelope_fails_closed():
    malformed = FIXTURE.read_text().replace("Mistral Large 4", r"\q", 1)
    with pytest.raises(ValueError):
        verify_current_card(URL, malformed, EXPECTED)


def test_new_card_pair_must_be_declared_together_not_historical():
    records = flight_records()
    declaration = next(node for node in _nodes(current_header(records)) if "names" in node[3])
    declaration[3]["names"] = ["new-snapshot", "new-latest"]
    records["fff"] = {"history": {"names": list(EXPECTED)}}
    assert verify_current_card(URL, encode(records), {"new-snapshot", "new-latest"}) == "active"
    with pytest.raises(ValueError):
        verify_current_card(URL, encode(records), EXPECTED)
