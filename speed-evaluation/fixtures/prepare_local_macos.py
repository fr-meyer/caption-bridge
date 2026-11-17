"""File-only local synthetic fixtures. No playback, network or redistribution.

Run on macOS with existing voices/ffmpeg. Outputs only a new private temp dir.
"""
import hashlib
import json
import math
import os
import platform
import struct
import subprocess
import tempfile
from pathlib import Path

TEXTS = {
    "en": ("Eddy (English (US))", "Pack six blue boxes. Pause, then count: one, two, three. The next train leaves at nine thirty."),
    "ko": ("Eddy (Korean (South Korea))", "파란 상자 여섯 개를 준비하세요. 잠시 쉬고, 하나, 둘, 셋. 다음 기차는 아홉 시 삼십 분에 출발합니다."),
}


def validate_pcm(data):
    if not data or len(data) % 4 or len(data) > 60*24000*4:
        raise ValueError("invalid PCM size")
    samples = [x[0] for x in struct.iter_unpack("<f", data)]
    if any(not math.isfinite(x) or abs(x) > 1 for x in samples):
        raise ValueError("invalid PCM samples")
    peak = max(abs(x) for x in samples)
    if peak < .001:
        raise ValueError("silent fixture")
    return dict(samples=len(samples), seconds=len(samples)/24000,
                peak=peak, sha256=hashlib.sha256(data).hexdigest())


def run(argv):
    return subprocess.run(argv, check=True, capture_output=True, timeout=45).stdout.decode()


def main():
    if platform.system() != "Darwin":
        raise SystemExit("macOS file-only recipe required")
    ffmpeg = "/opt/homebrew/bin/ffmpeg"
    voices = run(["/usr/bin/say", "-v", "?"])
    if any(voice not in voices for voice, _ in TEXTS.values()):
        raise SystemExit("required installed voices unavailable; do not download")
    root = Path(tempfile.mkdtemp(prefix="caption-offline-fixtures-", dir="/private/tmp"))
    os.chmod(root, 0o700)
    result = dict(scope="file-only local synthetic speech, not browser/human proof",
                  redistribution="NOT AUTHORIZED; binaries remain private local temp",
                  os=run(["/usr/bin/sw_vers"]),
                  decoder=run([ffmpeg, "-version"]).splitlines()[0],
                  voice_version="not independently exposed; bound to OS build and voice name",
                  directory=str(root), fixtures=[])
    for language, (voice, text) in TEXTS.items():
        source, target = root / (language+".aiff"), root / (language+".f32le")
        run(["/usr/bin/say", "-v", voice, "-r", "170", "-o", str(source), text])
        run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
             "-protocol_whitelist", "file,pipe", "-i", str(source), "-ac", "1",
             "-ar", "24000", "-f", "f32le", "-threads", "1", str(target)])
        result["fixtures"].append(dict(language=language, voice=voice, text=text,
                                        input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                        **validate_pcm(target.read_bytes())))
    (root / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
