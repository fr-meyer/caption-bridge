"""Local-source Worker wiring only: generated PCM, no audio APIs or providers."""
from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass


def main() -> None:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(QuietHandler, directory=str(Path(__file__).parent))
    )
    server.daemon_threads = True
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="chrome", headless=True, args=["--mute-audio"]
            )
            context = browser.new_context(permissions=[])
            page = context.new_page()
            page.set_default_timeout(10000)
            page.route(
                "**/*",
                lambda route: route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort(),
            )
            page.goto(origin)
            page.evaluate("""() => {
                window.audioApiCalls = 0;
                const denied = () => { audioApiCalls++; throw new Error('audio forbidden'); };
                window.AudioContext = function () { denied(); };
                window.webkitAudioContext = window.AudioContext;
                HTMLMediaElement.prototype.play = denied;
                navigator.mediaDevices.getUserMedia = denied;
            }""")
            page.add_script_tag(url=origin + "/transform-client.js")
            measurements = []
            for rate in (1.15, 1.3):
                result = page.evaluate("""async rate => {
                    const input = Float32Array.from({length: 48000}, (_, i) =>
                        0.4 * Math.sin(2 * Math.PI * 440 * i / 24000));
                    let terminated = 0;
                    const client = new CaptionSpeedTransformClient(() => {
                        const worker = new Worker('/wsola-worker.js');
                        const terminate = worker.terminate.bind(worker);
                        worker.terminate = () => { terminated++; terminate(); };
                        return worker;
                    });
                    const began = performance.now();
                    const result = await client.run(input, rate, {epoch: 2, clipId: 4});
                    const elapsed = performance.now() - began;
                    let first = null, last = null, count = 0;
                    for (let i = 3601; i < result.pcm.length - 3600; i++) {
                        if (result.pcm[i-1] <= 0 && result.pcm[i] > 0) {
                            const crossing = i - 1 + (-result.pcm[i-1]) /
                                (result.pcm[i] - result.pcm[i-1]);
                            if (first === null) first = crossing;
                            last = crossing; count++;
                        }
                    }
                    return {rate, output_samples: result.pcm.length, input_samples: input.length,
                        input_retained: input[5] !== 0, frequency_hz: (count-1)*24000/(last-first),
                        epoch: result.epoch, clip_id: result.clipId, worker_terminated: terminated,
                        active_job: client.active !== null, wall_ms_including_worker_startup: elapsed,
                        audio_api_calls: audioApiCalls};
                }""", rate)
                assert result["output_samples"] == int(48000 / rate)
                assert result["input_samples"] == 48000 and result["input_retained"]
                assert abs(result["frequency_hz"] - 440) < 1.32
                assert result["epoch"] == 2 and result["clip_id"] == 4
                assert result["worker_terminated"] == 1 and not result["active_job"]
                assert result["audio_api_calls"] == 0
                measurements.append(result)
            cancellation = page.evaluate("""async () => {
                let terminated = 0;
                const client = new CaptionSpeedTransformClient(() => {
                    const worker = new Worker('/wsola-worker.js');
                    const terminate = worker.terminate.bind(worker);
                    worker.terminate = () => { terminated++; terminate(); };
                    return worker;
                });
                const pending = client.run(new Float32Array(1440000), 1.3, {epoch: 2, clipId: 5});
                client.cancel();
                let outcome = 'unexpected_success';
                try { await pending; } catch (error) { outcome = error.name; }
                return {outcome, worker_terminated: terminated, active_job: client.active !== null,
                    audio_api_calls: audioApiCalls};
            }""")
            assert cancellation == {
                "outcome": "AbortError", "worker_terminated": 1,
                "active_job": False, "audio_api_calls": 0,
            }
            print(json.dumps({
                "schema_version": 1, "runtime": browser.version, "engine": "existing Chrome",
                "scope": "local-source Worker only; generated PCM never sent to audio API",
                "measurements": measurements, "cancellation": cancellation,
                "checks_passed": 3, "provider_requests": 0, "external_requests": 0,
                "native_safari": "not tested", "physical_windows": "not tested",
            }, indent=2))
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=1)


if __name__ == "__main__":
    main()
