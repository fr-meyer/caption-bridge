"""Hosted macOS CI only, bounded noaudio matrix, no capture authority."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(sys.argv[1]).resolve()
images = ("GuardianA", "GuardianB", "SyntheticHelper", "NoAudioController")
receipt = {"schema": 4, "qualification": "NO_AUDIO_ONLY", "images": {}, "rows": []}
for name in images:
    path = root / name
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(path)], check=True, timeout=3)
    receipt["images"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
subprocess.run([str(root / "StateMatrix")], check=True, timeout=3)
for mode in ("deadline", "guardian_a", "guardian_b", "helper", "suspend"):
    start = time.monotonic()
    child = subprocess.Popen([str(root / "NoAudioController"), "--noaudio", str(root), mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = child.communicate(timeout=7)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
    if len(out) > 4096 or len(err) > 4096:
        raise RuntimeError("bounded receipt exceeded")
    row = {"mode": mode, "exit": child.returncode, "elapsed_seconds": time.monotonic()-start, "receipt": json.loads(out)}
    receipt["rows"].append(row)
    assert child.returncode == 0, row
    assert row["receipt"]["terminal"] == "HOLD", row
print(json.dumps(receipt, sort_keys=True))
