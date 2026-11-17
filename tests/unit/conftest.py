"""Provider-free unit baseline: synthetic eligible account metadata.

This is NOT a claim that the real Medium alias is active. Selection/dispatch
unit tests need a valid prerequisite; catalogue lifecycle tests inject their own
empty/retired/conflicting metadata to exercise fail-closed behavior explicitly.
"""
import time

import pytest

from app import translation_models
from app.translation_catalogue import ModelCatalogue


@pytest.fixture(autouse=True)
def synthetic_model_catalogue(monkeypatch):
    catalogue = ModelCatalogue()
    catalogue.verified_at = time.monotonic()
    catalogue.public_verified_at = time.time()
    catalogue.entries = [
        dict(id=model, label=label, enabled=True, reason=None,
             efforts=translation_models.EXECUTION_POLICIES[model]["efforts"])
        for model, label in [
            ("mistral-medium-latest", "Mistral Medium (latest)"),
            ("mistral-small-latest", "Mistral Small (latest)"),
            ("mistral-large-latest", "Mistral Large (latest)"),
            ("mistral-large-4", "Mistral Large 4"),
            ("zai-glm-5-3", "Z.ai GLM 5.3"),
        ]
    ]
    monkeypatch.setattr(translation_models, "catalogue", catalogue)
    return catalogue
