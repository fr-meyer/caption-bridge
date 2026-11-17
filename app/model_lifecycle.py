"""Read-only official public lifecycle refresh; never account or inference traffic."""
from __future__ import annotations

import asyncio
import json
from html.parser import HTMLParser

import httpx

_STATUS = {"GA": "active", "Public Preview": "active", "Deprecated": "deprecated",
           "Retired": "retired"}


class _Badges(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.text = ""
        self.statuses = set()

    def handle_starttag(self, tag, attrs):
        if tag == "span" and dict(attrs).get("data-slot") == "badge":
            self.capture, self.text = True, ""

    def handle_data(self, data):
        if self.capture:
            self.text += data

    def handle_endtag(self, tag):
        if tag == "span" and self.capture:
            status = _STATUS.get(self.text.strip())
            if status:
                self.statuses.add(status)
            self.capture = False


def parse_lifecycle(html):
    parser = _Badges()
    parser.feed(html)
    if len(parser.statuses) != 1:
        raise ValueError("Official lifecycle status is missing or conflicting.")
    return parser.statuses.pop()


class _FlightScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script = False
        self.buffer = []
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script = True
            self.buffer = []

    def handle_data(self, data):
        if self.script:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script:
            self.script = False
            text = "".join(self.buffer)
            prefix = "self.__next_f.push("
            if text.startswith(prefix):
                payload = json.loads(text[len(prefix):-1])
                if isinstance(payload, list) and len(payload) == 2 and payload[0] == 1:
                    if not isinstance(payload[1], str):
                        raise ValueError("Malformed Flight stream")
                    self.chunks.append(payload[1])


def _nodes(value, records=None, ancestors=()):
    if isinstance(value, str) and value.startswith("$L") and records is not None:
        key = value[2:]
        if key in ancestors or len(ancestors) >= 32:
            raise ValueError("Cyclic current-card render reference")
        if key in records:
            yield from _nodes(records[key], records, (*ancestors, key))
    elif isinstance(value, list):
        if len(value) == 4 and value[0] == "$" and isinstance(value[3], dict):
            yield value
            yield from _nodes(value[3].get("children"), records, ancestors)
        else:
            for child in value:
                yield from _nodes(child, records, ancestors)


def verify_current_card(url, html, expected):
    """Decode JSON Flight framing, follow the canonical route's children outlet.

    Only the current page's inline header component owns names and lifecycle.
    Never search navigation/history records or union declarations across cards.
    Unknown transport/schema variants fail closed, rather than guessing.
    """
    parser = _FlightScripts()
    parser.feed(html)
    records = {}
    for line in "".join(parser.chunks).splitlines():
        key, separator, body = line.partition(":")
        if separator and key and all(char in "0123456789abcdef" for char in key):
            if body.startswith(("[", "{")):
                if key in records:
                    raise ValueError("Ambiguous Flight record")
                records[key] = json.loads(body)
    root = records.get("0", {})
    slug = url.removeprefix("https://docs.mistral.ai/models/")
    if "/" in slug or root.get("c") != ["", "en", "models", slug]:
        raise ValueError("Canonical current-card source mismatch")
    route = root["t"]["t"]
    seen = set()
    while route.get("s") != "__PAGE__":
        segment = route.get("s")
        if isinstance(segment, dict) and segment.get("n") == "slug" and segment.get("k") != slug:
            raise ValueError("Canonical current-card route segment mismatch")
        reference = route.get("c", "")
        if not isinstance(reference, str) or not reference.startswith("$Q") or reference in seen:
            raise ValueError("Unbound current-card route")
        seen.add(reference)
        outlets = records.get(reference[2:], [])
        children = [entry[1] for entry in outlets
                    if isinstance(entry, list) and len(entry) == 2 and entry[0] == "children"]
        if len(children) != 1:
            raise ValueError("Ambiguous current-card route")
        route = children[0]
    page = route["d"]["r"][3]["children"][0]
    if not isinstance(page, str) or not page.startswith("$L"):
        raise ValueError("Unbound current-card page")
    tree = records.get(page[2:])
    headers = [node for node in _nodes(tree, records)
               if {"rounded-md", "border", "relative", "flex-col", "gap-6", "p-5"}
               <= set(node[3].get("className", "").split())]
    if len(headers) != 1:
        raise ValueError("Missing or ambiguous current-card header")
    # In this supported provider schema the final direct header row contains
    # the title/description column and a sibling names component. Do not accept
    # a history/nav declaration merely nested somewhere inside the header.
    identity_row = headers[0][3]["children"][-1]
    if not (isinstance(identity_row, list) and len(identity_row) == 4 and
            identity_row[1] == "div" and
            "md:flex-row" in identity_row[3].get("className", "").split()):
        raise ValueError("Unknown current-card identity row")
    slots = identity_row[3].get("children")
    if not isinstance(slots, list) or len(slots) != 2:
        raise ValueError("Ambiguous current-card identity slots")
    declaration = slots[1]
    seen_names = set()
    while isinstance(declaration, str) and declaration.startswith("$L"):
        if declaration in seen_names:
            raise ValueError("Cyclic current-card identity slot")
        seen_names.add(declaration)
        declaration = records.get(declaration[2:])
    if not (isinstance(declaration, list) and len(declaration) == 4 and
            isinstance(declaration[3], dict) and "names" in declaration[3]):
        raise ValueError("Missing current-card identity declaration")
    nodes = list(_nodes(headers[0], records))
    titles = [node for node in nodes if node[1] == "h1" or node[3].get("as") == "h1"]
    declarations = [node[3]["names"] for node in nodes if "names" in node[3]]
    statuses = [node[3].get("children") for node in nodes
                if node[1] == "span" and node[3].get("data-slot") == "badge"
                and isinstance(node[3].get("children"), str)
                and node[3].get("children") in _STATUS]
    if len(titles) != 1 or len(declarations) != 1 or len(statuses) != 1:
        raise ValueError("Ambiguous current-card identity or lifecycle")
    names = declarations[0]
    if (not isinstance(names, list) or not names or
            not all(isinstance(name, str) and name for name in names) or
            len(names) != len(set(names)) or not expected <= set(names)):
        raise ValueError("Current-card model identities or aliases changed")
    return _STATUS[statuses[0]]


async def refresh_public_lifecycle(evidence, fetch=None):
    """Fixed official origins only; preserve identities, never invent aliases.

    Each verified current model card must have an unambiguous lifecycle badge.
    Removed/changed markup fails closed. Historical deprecated entries keep
    their original independent evidence, not the replacement's active status.
    """
    pages = {row["source"] for row in evidence.values() if row.get("refresh_public")}
    semaphore = asyncio.Semaphore(3)

    def verify(url, html):
        expected = {model for model, row in evidence.items()
                    if row.get("refresh_public") and row["source"] == url}
        return url, verify_current_card(url, html, expected)

    async def read_page(url):
        async with semaphore:
            if fetch is not None:
                return verify(url, await fetch(url))
            if not url.startswith("https://docs.mistral.ai/models/"):
                raise ValueError("Unexpected lifecycle source")
            async with httpx.AsyncClient(timeout=4, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 3_000_000:
                            raise ValueError("Public lifecycle response exceeds limit")
            return verify(url, content.decode("utf-8"))

    async with asyncio.timeout(8):
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(read_page(url)) for url in pages]
    statuses = dict(task.result() for task in tasks)
    return {model: dict(row, status=statuses[row["source"]]) if row.get("refresh_public") else dict(row)
            for model, row in evidence.items()}
