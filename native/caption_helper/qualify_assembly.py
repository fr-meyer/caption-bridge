"""Hosted macOS noaudio CI only. Never run on meeting Mac."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(sys.argv[1]).resolve()
images = ('GuardianA', 'GuardianB', 'SyntheticHelper', 'NoAudioController')
receipt = {'schema': 3, 'qualification': 'NO_AUDIO_ONLY', 'images': {}}
for name in images:
    path = root / name
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(path)], check=True,
                   timeout=5)
    receipt['images'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
start = time.monotonic()
result = subprocess.run([str(root / 'NoAudioController'), '--noaudio', str(root)],
                        capture_output=True, text=True, timeout=5)
receipt.update(exit=result.returncode, elapsed_seconds=time.monotonic()-start,
               stdout=result.stdout, stderr=result.stderr)
print(json.dumps(receipt, sort_keys=True))
assert result.returncode == 0
assert json.loads(result.stdout)['terminal'] == 'HOLD'
# This is an assembly smoke check, not yet a complete native failure-injection matrix.
