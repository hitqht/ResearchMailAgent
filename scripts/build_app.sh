#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
[[ "$(uname -s)" == Darwin ]] || { echo 'macOS is required'; exit 1; }
ARCH="$(uname -m)"
[[ "$ARCH" == arm64 || "$ARCH" == x86_64 ]] || { echo 'Unsupported architecture'; exit 1; }
VERSION="$(uv run --locked python -c 'from researchmail import __version__; print(__version__)')"
mkdir -p build artifacts
rm -rf build/pyinstaller dist/ResearchMailAgent.app dist/ResearchMailAgent
uv run --locked pyinstaller --clean --noconfirm --onedir --windowed \
  --name ResearchMailAgent --target-architecture "$ARCH" \
  --osx-bundle-identifier io.github.hitqht.ResearchMailAgent \
  --workpath build/pyinstaller --specpath build \
  --collect-data researchmail.storage.migrations \
  --hidden-import keyring.backends.macOS \
  --exclude-module tkinter --exclude-module PySide6.QtQml \
  --exclude-module PySide6.QtQuick packaging/launcher.py
test -x dist/ResearchMailAgent.app/Contents/MacOS/ResearchMailAgent
uv run --locked python - "$VERSION" "$ARCH" <<'PY'
import json, plistlib, sys
from pathlib import Path
bundle = Path('dist/ResearchMailAgent.app')
plist = bundle / 'Contents/Info.plist'
info = plistlib.loads(plist.read_bytes())
info.update(CFBundleShortVersionString=sys.argv[1], CFBundleVersion=sys.argv[1],
            NSHighResolutionCapable=True, LSMinimumSystemVersion='14.0')
plist.write_bytes(plistlib.dumps(info))
Path('artifacts/build-app.json').write_text(json.dumps({
    'version':sys.argv[1], 'architecture':sys.argv[2], 'bundle':str(bundle.resolve()),
    'distribution':'development', 'developer_id_signed':False, 'notarized':False,
}, indent=2))
PY
# Refresh the outer bundle after Info.plist changes; this uses only an ad-hoc identity.
codesign --force --sign - dist/ResearchMailAgent.app
codesign --verify --deep --strict dist/ResearchMailAgent.app
echo "Built $VERSION ($ARCH): ad-hoc development app, not notarized."
