"""Read-only official public lifecycle refresh; never account or inference traffic."""
from __future__ import annotations

import asyncio
import json
import re
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


async def refresh_public_lifecycle(evidence, fetch=None):
    """Fixed official origins only; preserve identities, never invent aliases.

    Each verified current model card must have an unambiguous lifecycle badge.
    Removed/changed markup fails closed. Historical deprecated entries keep
    their original independent evidence, not the replacement's active status.
    """
    pages = {row["source"] for row in evidence.values() if row.get("refresh_public")}
    semaphore = asyncio.Semaphore(3)

    def verify(url, html):
        # Model-card names are serialized inside Next flight script strings.
        normalized = html.replace(chr(92), "")
        groups = re.findall(r'"names":(\[[^\]]+\])', normalized)
        names = set()
        for group in groups:
            names.update(json.loads(group))
        expected = {model for model, row in evidence.items()
                    if row.get("refresh_public") and row["source"] == url}
        if not expected <= names:
            raise ValueError("Public model identities or aliases changed")
        return url, parse_lifecycle(html)

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
