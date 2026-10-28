#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
bash scripts/build_app.sh
VERSION="$(uv run --locked python -c 'from researchmail import __version__; print(__version__)')"
ARCH="$(uname -m)"
DMG="dist/ResearchMailAgent-${VERSION}-${ARCH}-dev.dmg"
STAGE="$(mktemp -d "$PWD/build/dmg.XXXXXX")"
MOUNT=""
cleanup() {
  if [[ -n "$MOUNT" ]]; then hdiutil detach "$MOUNT" >/dev/null || true; fi
  rm -rf "$STAGE"
}
trap cleanup EXIT
ditto dist/ResearchMailAgent.app "$STAGE/ResearchMailAgent.app"
ln -s /Applications "$STAGE/Applications"
bash scripts/create_dmg.sh "$STAGE" "$DMG" "ResearchMailAgent ${VERSION} Dev"
hdiutil verify "$DMG"
hdiutil attach -nobrowse -readonly -plist "$DMG" > artifacts/dmg-mount.plist
MOUNT="$(uv run --locked python - <<'PY'
import plistlib
with open('artifacts/dmg-mount.plist','rb') as stream:
    data = plistlib.load(stream)
print(next(item['mount-point'] for item in data['system-entities'] if 'mount-point' in item))
PY
)"
test -x "$MOUNT/ResearchMailAgent.app/Contents/MacOS/ResearchMailAgent"
test "$(readlink "$MOUNT/Applications")" = /Applications
codesign --verify --deep --strict "$MOUNT/ResearchMailAgent.app"
shasum -a 256 "$DMG" > "${DMG}.sha256"
uv run --locked python - "$DMG" <<'PY'
import hashlib, json, sys
from pathlib import Path
path = Path(sys.argv[1])
Path('artifacts/build-dmg.json').write_text(json.dumps({
    'dmg':str(path.resolve()), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    'mount_verified':True,'applications_symlink_verified':True,
    'distribution':'development','developer_id_signed':False,'notarized':False,
},indent=2))
PY
echo "Created $DMG (development; not Developer ID signed or notarized)."
