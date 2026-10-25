"""Explicit Windows software fixture; native audio/providers are disabled."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def build_app(runtime_root: Path, port: int):
    calls = {"native": 0, "provider": 0}

    def denied(kind):
        def reject(*_args, **_kwargs):
            calls[kind] += 1
            raise RuntimeError("software_fixture_external_io_denied")

        return reject

    for key in list(os.environ):
        if key.upper().startswith("MISTRAL_"):
            os.environ.pop(key)
    from pydantic_settings.sources import DotEnvSettingsSource

    DotEnvSettingsSource._read_env_files = lambda _self: {}
    sd = ModuleType("sounddevice")
    fixture_device = {
        "name": "Offline simulated input",
        "max_input_channels": 1,
        "max_output_channels": 0,
        "default_samplerate": 16000.0,
        "hostapi": 0,
    }
    sd.query_devices = lambda device=None, kind=None: (
        dict(fixture_device) if device is not None or kind is not None else [dict(fixture_device)]
    )
    sd.query_hostapis = lambda *_args, **_kwargs: [{"name": "Offline simulated host API"}]
    sd.default = SimpleNamespace(device=(0, -1))
    sd.check_input_settings = lambda **_kwargs: None
    for name in ("RawInputStream", "RawOutputStream", "InputStream", "OutputStream", "play"):
        setattr(sd, name, denied("native"))
    sys.modules["sounddevice"] = sd
    import mistralai.client

    async def provider(*_args, **_kwargs):
        denied("provider")()

    class FixtureClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(complete_async=provider)
            self.audio = SimpleNamespace(
                speech=SimpleNamespace(complete_async=provider),
                realtime=SimpleNamespace(connect=provider),
            )

    mistralai.client.Mistral = FixtureClient
    if "app.providers" in sys.modules:
        sys.modules["app.providers"].Mistral = FixtureClient
    from app import config, readiness
    from app.state import ReadinessCheck

    config.settings = config.AppConfig(
        _env_file=None,
        MISTRAL_API_KEY="offline-fixture-only",
        MISTRAL_TTS_ENABLED=False,
        HOST="127.0.0.1",
        PORT=port,
        journal_dir=str(runtime_root / "journal"),
        export_dir=str(runtime_root / "exports"),
        recovery_export_dir=str(runtime_root / "recovered"),
        reliability_dir=str(runtime_root / "reliability"),
    )
    readiness._check_mic_available = lambda: ReadinessCheck(
        name="Fixture microphone",
        key="mic_available",
        ready=False,
        detail="Software fixture: no native input",
    )
    readiness._check_mic_permission = lambda: ReadinessCheck(
        name="Fixture permission",
        key="mic_permission",
        ready=False,
        detail="Software fixture: permission is not queried",
    )
    from app import main, ws

    ws.settings = config.settings

    @main.app.get("/software/fixture-proof")
    async def proof():
        return {
            "software_fixture": True,
            "native_input_enabled": False,
            "native_calls": calls["native"],
            "provider_calls": calls["provider"],
            "capture_active": main.manager._reliability.pipeline.capture_active,
        }

    main.app.router.routes.insert(0, main.app.router.routes.pop())
    return main.app, calls


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.software_network_guard import SoftwareNetworkGuard

    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("software_fixture_port_invalid")
    def deny(*_args, **_kwargs):
        raise RuntimeError("software_fixture_outbound_denied")

    guard = SoftwareNetworkGuard(deny).install()
    try:
        listener = guard.create_listener(args.port)
        app, _calls = build_app(args.runtime_root, args.port)
        import uvicorn

        config = uvicorn.Config(
            app, host="127.0.0.1", port=args.port, loop="asyncio", log_level="warning"
        )
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        guard.close()


if __name__ == "__main__":
    main()
