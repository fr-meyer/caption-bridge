"""Loopback-only synthetic backend for production frontend browser contracts."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from app.config import AppConfig
from app.profiles import available_profiles, resolve_profile

STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
_STARTED_AT = "2026-01-01T00:00:00+00:00"
_ENDED_AT = "2026-01-01T00:01:00+00:00"


def _segment(
    seq: int,
    *,
    source: str,
    translated: str | None,
    status: str,
) -> dict[str, Any]:
    return {
        "id": f"synthetic-{seq}",
        "seq": seq,
        "created_at": _STARTED_AT,
        "source_text": source,
        "segment_kind": "complete",
        "translated_text": translated,
        "target_language": "en",
        "translation_status": status,
        "translated_at": _ENDED_AT,
        "quality": None,
        "failure_reason": None,
    }


def _snapshot(scenario: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "type": "session_snapshot",
        "status": "idle_ready",
        "checks": [
            {
                "name": "Synthetic browser backend",
                "key": "synthetic",
                "ready": True,
                "detail": "Ready",
            }
        ],
        "source_partial": "",
        "segments": [],
        "exported": False,
        "export_path": None,
        "export_failure": None,
        "recovery_notice": None,
        "source_language": "auto",
        "target_language": "en",
        "caption_profile": resolve_profile("current", AppConfig(_env_file=None)).model_dump(mode="json"),
        "available_caption_profiles": available_profiles(AppConfig(_env_file=None)),
        "translation_model": "mistral-small-latest",
        "available_translation_models": [
            {"id": "mistral-small-latest", "label": "Mistral Small (latest)"},
            {"id": "mistral-medium-latest", "label": "Mistral Medium (latest)"},
            {"id": "zai-glm-5-3", "label": "Z.ai GLM 5.3 (preview)"},
        ],
        "available_target_languages": [{"code": "en", "label": "English"}],
        "started_at": None,
        "ended_at": None,
        "tts_epoch": 0,
    }
    if scenario == "degraded":
        snapshot.update(
            status="session_ended",
            started_at=_STARTED_AT,
            ended_at=_ENDED_AT,
            segments=[
                _segment(
                    1,
                    source="Synthetic degraded source one.",
                    translated=None,
                    status="timed_out",
                ),
                _segment(
                    2,
                    source="Synthetic degraded source two.",
                    translated=None,
                    status="failed",
                ),
            ],
        )
    elif scenario == "restored":
        snapshot.update(
            status="listening",
            started_at=_STARTED_AT,
            segments=[
                _segment(
                    1,
                    source="Synthetic restored source.",
                    translated="Synthetic restored caption.",
                    status="done",
                )
            ],
        )
    elif scenario in {"export", "export_failure"}:
        snapshot.update(
            status="session_ended",
            started_at=_STARTED_AT,
            ended_at=_ENDED_AT,
            export_failure=(
                {"error": "Synthetic export failed"}
                if scenario == "export_failure"
                else None
            ),
            segments=[
                _segment(
                    1,
                    source="Synthetic export source.",
                    translated="Synthetic export caption.",
                    status="done",
                )
            ],
        )
    elif scenario == "profiles_restored":
        snapshot.update(status="listening", started_at=_STARTED_AT,
                        caption_profile=resolve_profile("longer", AppConfig(_env_file=None)).model_dump(mode="json"))
    elif scenario == "glossary_idle":
        snapshot["available_target_languages"].append({"code": "fr", "label": "French"})
    elif scenario != "idle_ready":
        raise ValueError(f"unsupported browser scenario: {scenario}")
    return snapshot


@dataclass
class BrowserHarness:
    url: str = ""
    scenario: str = "idle_ready"
    messages: list[dict[str, Any]] = field(default_factory=list)
    connections: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def configure(self, scenario: str) -> None:
        _snapshot(scenario)
        with self._lock:
            self.scenario = scenario
            self.messages.clear()
            self.connections = 0

    def on_connect(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self._lock:
            self.connections += 1
            scenario = self.scenario
        events: list[dict[str, Any]] = []
        if scenario == "degraded":
            events = [
                {
                    "type": "provider_capacity_warning",
                    "reason": "service_tier_capacity_exceeded",
                    "status_code": 429,
                    "segment_seq": 2,
                },
                {
                    "type": "provider_temporarily_unavailable",
                    "service": "transcription",
                    "outcome": "exhausted",
                    "attempts": 3,
                    "max_attempts": 3,
                },
            ]
        return _snapshot(scenario), events

    def record(self, message: dict[str, Any]) -> None:
        with self._lock:
            self.messages.append(message)

    def message_count(self, message_type: str) -> int:
        with self._lock:
            return sum(
                message.get("type") == message_type for message in self.messages
            )

    def wait_for_message(
        self, message_type: str, *, timeout_s: float = 2.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                match = next(
                    (
                        message
                        for message in self.messages
                        if message.get("type") == message_type
                    ),
                    None,
                )
            if match is not None:
                return match
            time.sleep(0.01)
        raise AssertionError(f"browser message not received: {message_type}")

    def wait_for_connections(self, count: int, *, timeout_s: float = 2.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self.connections >= count:
                    return
            time.sleep(0.01)
        raise AssertionError(f"browser connection count did not reach {count}")


def _create_app(harness: BrowserHarness) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> Response:
        return Response(status_code=204)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/app.js")
    async def app_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

    @app.get("/styles.css")
    async def styles() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        snapshot, initial_events = harness.on_connect()
        await websocket.send_bytes(orjson.dumps(snapshot))
        for event in initial_events:
            await websocket.send_bytes(orjson.dumps(event))
        try:
            while True:
                message = orjson.loads(await websocket.receive_text())
                harness.record(message)
                message_type = message.get("type")
                if message_type == "start":
                    await websocket.send_bytes(
                        orjson.dumps(
                            {
                                "type": "status",
                                "status": "listening",
                                "started_at": _STARTED_AT,
                            }
                        )
                    )
                elif message_type == "set_translation_model":
                    await websocket.send_bytes(orjson.dumps({
                        "type": "translation_model_changed",
                        "model": message["model"],
                        "revision": 1,
                        "applies_from_seq": 2,
                    }))
                elif message_type == "stop":
                    await websocket.send_bytes(
                        orjson.dumps(
                            {"type": "status", "status": "session_ended"}
                        )
                    )
                elif message_type == "export":
                    await websocket.send_bytes(
                        orjson.dumps(
                            {
                                "type": "export_result",
                                "success": True,
                                "path": "synthetic/export",
                                "error": None,
                            }
                        )
                    )
                elif message_type == "new_session":
                    await websocket.send_bytes(orjson.dumps(_snapshot("idle_ready")))
        except WebSocketDisconnect:
            return

    return app


@pytest.fixture(scope="session")
def browser_harness() -> BrowserHarness:
    harness = BrowserHarness()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    harness.url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(
        _create_app(harness),
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="browser-e2e-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{harness.url}/healthz", timeout=0.2)
            if response.status_code == 204:
                break
        except httpx.HTTPError:
            time.sleep(0.02)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("browser fixture server did not start")

    yield harness

    server.should_exit = True
    thread.join(timeout=5)
    if thread.is_alive():
        raise AssertionError("browser fixture server did not stop")
