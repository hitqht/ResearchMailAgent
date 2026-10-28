#!/bin/bash
# Retry only the observed transient hdiutil device-busy failure.
set -euo pipefail
[[ $# == 3 ]] || { echo 'Usage: create_dmg.sh STAGE OUTPUT VOLUME' >&2; exit 2; }
DMG_STAGE="$1"
DMG_OUTPUT="$2"
DMG_LABEL="$3"
DMG_ERROR="$(mktemp "${TMPDIR:-/tmp}/researchmail-hdiutil.XXXXXX")"
trap 'rm -f "$DMG_ERROR"' EXIT
for DMG_ATTEMPT in 1 2 3; do
  if LC_ALL=C hdiutil create -volname "$DMG_LABEL" -srcfolder "$DMG_STAGE" \
      -format UDZO -ov -o "$DMG_OUTPUT" 2>"$DMG_ERROR"; then
    exit 0
  fi
  cat "$DMG_ERROR" >&2
  if [[ "$DMG_ATTEMPT" == 3 ]] || ! grep -q 'Resource busy' "$DMG_ERROR"; then
    exit 1
  fi
  sleep "$DMG_ATTEMPT"
done
exit 1
