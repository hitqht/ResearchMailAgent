import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure,expected_count,expected_code", [("busy", 3, 0), ("denied", 1, 1)])
def test_image_creation_only_retries_device_busy(tmp_path, failure, expected_count, expected_code):
    binary = tmp_path / "hdiutil"
    binary.write_text("""#!/bin/bash
n=0
[[ ! -e "$DMG_TEST_COUNT" ]] || n=$(cat "$DMG_TEST_COUNT")
n=$((n+1))
echo "$n" > "$DMG_TEST_COUNT"
if [[ "$DMG_TEST_FAILURE" == busy && "$n" -lt 3 ]]; then
  echo 'hdiutil: create failed - Resource busy' >&2
  exit 1
fi
if [[ "$DMG_TEST_FAILURE" == denied ]]; then
  echo 'hdiutil: create failed - Permission denied' >&2
  exit 1
fi
exit 0
""")
    binary.chmod(0o700)
    count = tmp_path / "count"
    env = {
        **os.environ,
        "PATH": str(tmp_path) + ":" + os.environ["PATH"],
        "DMG_TEST_COUNT": str(count),
        "DMG_TEST_FAILURE": failure,
    }
    result = subprocess.run(
        [
            "bash",
            str(Path("scripts/create_dmg.sh").resolve()),
            str(tmp_path / "stage"),
            str(tmp_path / "test.dmg"),
            "Test",
        ],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == expected_code
    assert int(count.read_text()) == expected_count
