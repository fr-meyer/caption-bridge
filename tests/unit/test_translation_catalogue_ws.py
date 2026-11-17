"""Metadata refresh cannot block commands or survive its owning connection."""
import asyncio
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ws
from app.config import AppConfig
from app.state import SessionManager
from app.translation_catalogue import ModelCatalogue


def test_refresh_remains_responsive_and_disconnect_cancels_public_fetch(tmp_path, monkeypatch):
    entered, cancelled = threading.Event(), threading.Event()
    async def public(evidence):
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()
    async def account():
        return []
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False,
                       JOURNAL_DIR=str(tmp_path / "journal"),
                       RELIABILITY_DIR=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(ws, "catalogue", ModelCatalogue(timeout=10))
    monkeypatch.setattr(ws, "catalogue_loader", account)
    monkeypatch.setattr(ws, "refresh_public_lifecycle", public)
    monkeypatch.setattr(ws, "_active_connection", None)
    app = FastAPI()
    app.add_api_websocket_route("/ws", ws.websocket_endpoint)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json(mode="binary")["type"] == "connection_lifecycle"
            assert socket.receive_json(mode="binary")["type"] == "session_snapshot"
            socket.send_json({"type": "refresh_translation_models"})
            assert entered.wait(2)
            socket.send_json({"type": "set_translation_model", "model": "not-eligible"})
            assert socket.receive_json(mode="binary")["type"] == "error"
    assert cancelled.wait(2)


def test_refresh_emits_catalogue_not_playback_reset_snapshot(tmp_path, monkeypatch):
    async def public(evidence):
        return evidence
    async def account():
        return [dict(id="mistral-large-4", aliases=["mistral-large-latest"],
                     capabilities={"completion_chat": True})]
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False,
                       JOURNAL_DIR=str(tmp_path / "journal"),
                       RELIABILITY_DIR=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(ws, "catalogue", ModelCatalogue(timeout=10))
    monkeypatch.setattr(ws, "catalogue_loader", account)
    monkeypatch.setattr(ws, "refresh_public_lifecycle", public)
    monkeypatch.setattr(ws, "_active_connection", None)
    app = FastAPI()
    app.add_api_websocket_route("/ws", ws.websocket_endpoint)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.receive_json(mode="binary")
            socket.receive_json(mode="binary")
            socket.send_json({"type": "refresh_translation_models"})
            result = socket.receive_json(mode="binary")
            assert result["type"] == "translation_catalogue"
            assert result["translation_catalogue"]["fresh"]
            assert result["translation_catalogue"]["public_verified_at"] is not None
            assert manager.session.translation_model_revision == 0
