"""Explicit offline-only catalogue scope for fake-provider evaluation entrypoints.

Runs are serialized: this context restores the process catalogue on every exit.
It never enumerates an account, qualifies a real model, or modifies defaults.
"""
import time
from contextlib import asynccontextmanager

from app import translation_models
from app.translation_catalogue import ModelCatalogue

SYNTHETIC_MODEL = "mistral-small-latest"


@asynccontextmanager
async def synthetic_translation_catalogue():
    previous = translation_models.catalogue
    cache = ModelCatalogue(clock=lambda: 0.0)
    async def load():
        return [{"id": "mistral-small-2603", "aliases": [SYNTHETIC_MODEL],
                 "capabilities": {"completion_chat": True, "reasoning": True}}]
    evidence = {
        SYNTHETIC_MODEL: {"status": "active", "family": "synthetic-small",
                          "alias": SYNTHETIC_MODEL, "source": "synthetic-offline-fixture"},
        "mistral-small-2603": {"status": "active", "family": "synthetic-small",
                                "source": "synthetic-offline-fixture"},
    }
    await cache.refresh(load, evidence, translation_models.EXECUTION_POLICIES)
    cache.public_verified_at = time.time()
    translation_models.catalogue = cache
    try:
        yield cache
    finally:
        translation_models.catalogue = previous
