#!/usr/bin/env bash
# Wrap packaging/build/dist/DeskDot.app (from PyInstaller) in a drag-to-Applications disk image.
#
#   bash packaging/macos/build_dmg.sh 3.8.0 arm64     → packaging/build/installer/DeskDot-3.8.0-macOS-arm64.dmg
#
# The app is ad-hoc signed (no Apple Developer ID): first launch needs right-click → Open (docs/DEPLOY.md).
# With MACOS_SIGN_IDENTITY set (a "Developer ID Application: …" identity in the keychain) it is signed with that
# instead, and with MACOS_NOTARY_PROFILE (a `xcrun notarytool store-credentials` profile) the dmg is notarized.
set -euo pipefail

VERSION="${1:?version}"
ARCH="${2:?arch (arm64 | x64)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/packaging/build/dist/DeskDot.app"
OUT="$ROOT/packaging/build/installer"
DMG="$OUT/DeskDot-$VERSION-macOS-$ARCH.dmg"
STAGE="$(mktemp -d)"

[ -d "$APP" ] || { echo "missing $APP (run pyinstaller first)"; exit 1; }
mkdir -p "$OUT"

if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$MACOS_SIGN_IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

cp -R "$APP" "$STAGE/DeskDot.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
# hdiutil on CI runners sometimes fails with "Resource busy" while macOS is still scanning the fresh files: retry.
for attempt in 1 2 3 4 5; do
  if hdiutil create -volname "DeskDot $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -imagekey zlib-level=9 -ov "$DMG"; then
    break
  fi
  if [ "$attempt" = 5 ]; then echo "hdiutil failed 5 times" >&2; exit 1; fi
  echo "hdiutil busy (attempt $attempt), retrying in $((attempt * 10)) s" >&2
  # a half-made image or a volume left mounted by the failed try keeps the next one busy too
  rm -f "$DMG"
  for vol in /Volumes/DeskDot*; do [ -d "$vol" ] && hdiutil detach "$vol" -force >/dev/null 2>&1 || true; done
  sync
  sleep $((attempt * 10))
done
rm -rf "$STAGE"
# a truncated image would only fail on the user's Mac: check it here
hdiutil verify "$DMG" >/dev/null || { echo "the disk image doesn't verify" >&2; exit 1; }

if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  codesign --force --sign "$MACOS_SIGN_IDENTITY" "$DMG"
  if [ -n "${MACOS_NOTARY_PROFILE:-}" ]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$MACOS_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  fi
fi
echo "$DMG"
