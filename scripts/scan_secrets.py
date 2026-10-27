"""Scan tracked/staged source before public commits; never print secret values."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(
    r"(?:\.(?:db(?:-\w+)?|sqlite[^/]*|eml|mbox|msg|log|pem|key|p12|pfx)$|\.env(?:\.|$))",
    re.I,
)


def main() -> int:
    files = (
        subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .split("\0")
    )
    forbidden = [path for path in files if path and FORBIDDEN.search(path)]
    # detect-secrets output is captured, so potential secret material is never printed.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--no-verify",
            *(path for path in files if path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    findings = json.loads(result.stdout)["results"]
    if forbidden or findings:
        print("Security scan failed. Inspect these files locally:")
        for path in sorted(set(forbidden) | set(findings)):
            print(path)
        return 1
    print("Secret scan passed; no forbidden data files tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
