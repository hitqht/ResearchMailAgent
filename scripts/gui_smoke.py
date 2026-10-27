"""Run the isolated self-test that also ships in the standalone app."""

import argparse
from pathlib import Path

from researchmail.diagnostics import self_test

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/gui"))
    parser.add_argument("--appearance", choices=("system", "light", "dark"), default="system")
    args = parser.parse_args()
    raise SystemExit(self_test(args.output, args.appearance))
