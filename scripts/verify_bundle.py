"""Validate standalone startup and isolated Applications copies without a developer PATH."""

import argparse
import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path


def run_app(app: Path, output: Path) -> dict[str, object]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "UV_"))
    }
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    subprocess.run(
        [str(app / "Contents/MacOS/ResearchMailAgent"), "--self-test", str(output)],
        env=environment,
        check=True,
        timeout=45,
        capture_output=True,
    )
    report = json.loads((output / "smoke.json").read_text())
    if not report.get("ok") or not report.get("frozen"):
        raise RuntimeError("Packaged startup validation failed")
    return dict(report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dmg", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    reports = {
        "bundle": run_app(root / "dist/ResearchMailAgent.app", root / "artifacts/bundle-smoke")
    }
    result = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-plist", str(args.dmg)],
        check=True,
        capture_output=True,
    )
    mounted = plistlib.loads(result.stdout)
    mount = next(
        Path(item["mount-point"]) for item in mounted["system-entities"] if "mount-point" in item
    )
    try:
        reports["mounted"] = run_app(
            mount / "ResearchMailAgent.app", root / "artifacts/mounted-smoke"
        )
        with tempfile.TemporaryDirectory(prefix="researchmail-install-") as directory:
            installed = Path(directory) / "Applications/ResearchMailAgent.app"
            installed.parent.mkdir()
            subprocess.run(
                ["ditto", str(mount / "ResearchMailAgent.app"), str(installed)], check=True
            )
            reports["copied_installation"] = run_app(installed, root / "artifacts/installed-smoke")
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)
    (root / "artifacts/bundle-verification.json").write_text(json.dumps(reports, indent=2))
    print("Standalone bundle, mounted DMG and isolated Applications copy all started successfully.")


if __name__ == "__main__":
    main()
