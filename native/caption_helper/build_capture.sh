#!/bin/sh
# Opt-in source build only. NEVER invokes either input executable.
# Existing noaudio build entrypoint deliberately remains unchanged.
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'macOS required' >&2; exit 64; }
[ "$#" = 1 ] && [ ! -e "$1" ] || { echo 'new output directory required' >&2; exit 64; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
umask 077
sh "$ROOT/scripts/build_caption_helper.sh" "$1"
OUT=$(CDPATH= cd -- "$1" && pwd)
BIN="$OUT/CaptionHelper.app/Contents/MacOS"
cat > "$OUT/CaptureHelper-Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>local.captionbridge.CaptureHelper</string>
<key>CFBundleName</key><string>CaptureHelper</string>
<key>CFBundleExecutable</key><string>CaptureHelper</string>
<key>CFBundleVersion</key><string>1</string>
<key>NSMicrophoneUsageDescription</key><string>Bounded, explicitly admitted local input safety check.</string>
</dict></plist>
PLIST
/usr/bin/plutil -lint "$OUT/CaptureHelper-Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string Bounded, explicitly admitted local input safety check." "$OUT/CaptionHelper.app/Contents/Info.plist"
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -Os  "$ROOT/native/caption_helper/capture_role.c" "$ROOT/native/caption_helper/capture_input.c"  -Wl,-sectcreate,__TEXT,__info_plist,"$OUT/CaptureHelper-Info.plist"  -framework AudioUnit -framework AudioToolbox -framework CoreAudio -framework CoreFoundation  -o "$BIN/CaptureHelper"
/usr/bin/codesign --sign - --identifier local.captionbridge.CaptureHelper --options runtime  --timestamp=none --entitlements "$ROOT/native/caption_helper/capture_entitlements.plist" "$BIN/CaptureHelper"
# Separate capture guardians; never replace the noaudio GuardianA/B images.
for SPEC in A:1 B:2; do
 NAME=CaptureGuardian${SPEC%:*}; ROLE=${SPEC#*:}
 /usr/bin/clang -std=c11 -Wall -Wextra -Werror -Os -DCAPTION_ROLE="$ROLE" "$ROOT/native/caption_helper/capture_guardian.c" -o "$BIN/$NAME"
 /usr/bin/codesign --sign - --identifier "local.captionbridge.$NAME" --options runtime --timestamp=none "$BIN/$NAME"
done
python3 "$ROOT/native/caption_helper/generate_capture_pins.py" "$BIN" "$OUT/capture_pins.h"
/usr/bin/clang -Wall -Wextra -Werror -Os -I"$OUT"  "$ROOT/native/caption_helper/capture_controller.c" -framework Security -framework CoreFoundation -lproc -o "$BIN/CaptureController"
/usr/bin/codesign --sign - --identifier local.captionbridge.capture.controller --options runtime  --timestamp=none "$BIN/CaptureController"
/usr/bin/codesign --force --sign - --options runtime --timestamp=none  --entitlements "$ROOT/native/caption_helper/entitlements.plist" "$OUT/CaptionHelper.app"
/usr/bin/codesign --verify --deep --strict "$OUT/CaptionHelper.app"
