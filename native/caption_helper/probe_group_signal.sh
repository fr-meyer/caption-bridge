#!/bin/sh
# Hosted Darwin only. Creates real owned noaudio processes, never capture images.
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'hosted Darwin required' >&2; exit 64; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] && [ ! -e "$1" ] || {
 echo 'usage: probe_group_signal.sh NEW_OUTPUT_DIR [CAPTURE_MACOS_BIN_DIR]' >&2
 exit 64
}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
umask 077
mkdir -- "$1"
OUT=$(CDPATH= cd -- "$1" && pwd)
{
 /usr/bin/sw_vers
 /usr/bin/uname -mrs
 /usr/sbin/sysctl kern.osrelease kern.osversion kern.version
 /usr/bin/id
 /usr/bin/clang --version
 printf 'diagnostic_only=true\ncapture=false\nnative_admission=false\n'
} > "$OUT/runtime.txt" 2>&1
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -Os \
 "$ROOT/native/caption_helper/probe_group_signal.c" -o "$OUT/GroupSignalProbe" \
 > "$OUT/build.stdout" 2> "$OUT/build.stderr"
# Same runtime signing option and no entitlements as the source CaptureController.
# Forked members share this signature; this is not the production exec topology.
/usr/bin/codesign --sign - --identifier local.captionbridge.group-signal-probe \
 --options runtime --timestamp=none "$OUT/GroupSignalProbe" \
 > "$OUT/sign.stdout" 2> "$OUT/sign.stderr"
/usr/bin/codesign --verify --strict "$OUT/GroupSignalProbe" \
 > "$OUT/verify.stdout" 2> "$OUT/verify.stderr"
/usr/bin/codesign --display --verbose=4 --entitlements :- "$OUT/GroupSignalProbe" \
 > "$OUT/probe.entitlements.plist" 2> "$OUT/probe.signature.txt"
/usr/bin/shasum -a 256 "$ROOT/native/caption_helper/probe_group_signal.c" \
 "$ROOT/native/caption_helper/probe_group_signal.sh" "$OUT/GroupSignalProbe" \
 > "$OUT/source-binary.sha256"
# Read-only evidence of the actual candidate, if already built by the CI lane.
# Missing or unverifiable candidate metadata fails this invocation, never waived.
if [ "$#" = 2 ]; then
 CANDIDATE=$(CDPATH= cd -- "$2" && pwd)
 for NAME in CaptureController CaptureGuardianA CaptureGuardianB CaptureHelper; do
  IMAGE="$CANDIDATE/$NAME"
  [ -f "$IMAGE" ] || { echo "missing candidate image: $NAME" >&2; exit 70; }
  /usr/bin/codesign --verify --strict "$IMAGE" \
   > "$OUT/$NAME.verify.stdout" 2> "$OUT/$NAME.verify.stderr"
  /usr/bin/codesign --display --verbose=4 --entitlements :- "$IMAGE" \
   > "$OUT/$NAME.entitlements.plist" 2> "$OUT/$NAME.signature.txt"
  /usr/bin/shasum -a 256 "$IMAGE" >> "$OUT/candidate-binaries.sha256"
 done
fi
set +e
"$OUT/GroupSignalProbe" > "$OUT/observations.jsonl" 2> "$OUT/probe.stderr"
RC=$?
set -e
printf 'probe_exit=%s\ndiagnostic_only=true\ncapture=false\nnative_admission=false\n' "$RC" \
 > "$OUT/result.txt"
cat "$OUT/observations.jsonl"
exit "$RC"
