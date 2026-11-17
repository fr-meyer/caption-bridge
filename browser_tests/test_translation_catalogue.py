"""Synthetic browser controls. No provider calls, audio or capture."""
import pytest
from playwright.sync_api import expect

import browser_tests.conftest as harness_module


@pytest.mark.browser
@pytest.mark.parametrize("reason", ["lifecycle_retired", "lifecycle_unknown", "execution_policy_unverified"])
def test_disabled_models_and_explicit_metadata_refresh(page, browser_harness, monkeypatch, reason):
    original = harness_module._snapshot
    def snapshot(scenario):
        data = original(scenario)
        data["available_translation_models"] = [
            {"id": "mistral-medium-latest", "label": "Medium", "enabled": True,
             "efforts": ["default", "high"]},
            {"id": "hosted-new", "label": "Hosted", "enabled": False,
             "reason": reason, "efforts": ["default"]},
        ]
        return data
    monkeypatch.setattr(harness_module, "_snapshot", snapshot)
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    option = page.locator("#idle-model-select option[value='hosted-new']")
    expect(option).to_be_disabled()
    expect(option).to_contain_text(reason)
    page.get_by_role("button", name="Refresh model metadata (no inference)").click()
    assert browser_harness.wait_for_message("refresh_translation_models") == {
        "type": "refresh_translation_models"}
    assert not any(message.get("type") == "start" for message in browser_harness.messages)


@pytest.mark.browser
def test_restored_retired_identity_is_visible_without_switch(page, browser_harness, monkeypatch):
    original = harness_module._snapshot
    def snapshot(scenario):
        data = original(scenario)
        data["translation_model"] = "retired-session-model"
        data["available_translation_models"] = [
            {"id": "mistral-medium-latest", "label": "Medium", "enabled": True,
             "efforts": ["default"]}]
        return data
    monkeypatch.setattr(harness_module, "_snapshot", snapshot)
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    expect(page.locator("#idle-model-select")).to_have_value("retired-session-model")
    expect(page.locator("#idle-model-select option[value='retired-session-model']")).to_be_disabled()
    assert not any(message.get("type") == "set_translation_model" for message in browser_harness.messages)
