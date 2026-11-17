#!/bin/sh
# Build only into a NEW directory. No launch, install, credentials or capture.
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'macOS required' >&2; exit 64; }
[ "$#" = 1 ] && [ ! -e "$1" ] || { echo 'new output directory required' >&2; exit 64; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
umask 077
mkdir -p "$1/CaptionHelper.app/Contents/MacOS"
APP="$1/CaptionHelper.app"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>local.captionbridge.qualification</string>
<key>CFBundleExecutable</key><string>CaptionHelper</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST
/usr/bin/clang -Wall -Wextra -Werror -Os "$ROOT/native/caption_helper/main.c" "$ROOT/native/caption_helper/supervised.c" -o "$APP/Contents/MacOS/CaptionHelper"
/usr/bin/codesign --sign - --options runtime --timestamp=none --entitlements "$ROOT/native/caption_helper/entitlements.plist" "$APP"
/usr/bin/codesign --verify --strict --verbose=2 "$APP"
/usr/bin/codesign -d --entitlements :- "$APP"
