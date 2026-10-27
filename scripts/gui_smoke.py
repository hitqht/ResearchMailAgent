"""Real Qt event-loop smoke test with isolated data, screenshot, and JSON report."""

import argparse
import json
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from researchmail.config import AppPaths
from researchmail.gui.window import MainWindow
from researchmail.services.workspace import WorkspaceService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/gui"))
    parser.add_argument("--appearance", choices=("system", "light", "dark"), default="system")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setApplicationName("ResearchMailAgent Smoke")
    if args.appearance != "system":
        scheme = Qt.ColorScheme.Dark if args.appearance == "dark" else Qt.ColorScheme.Light
        app.styleHints().setColorScheme(scheme)
    outcome = {"ok": False, "error": "Startup timed out"}
    with tempfile.TemporaryDirectory(prefix="researchmail-smoke-") as directory:
        root = Path(directory)
        service = WorkspaceService(AppPaths(root / "data", root / "logs"))
        window = MainWindow(service)
        window.show()

        def capture() -> None:
            if not window.ready or window.jobs:
                return
            if window.wizard is not None:
                window.wizard.grab().save(str(args.output / "onboarding.png"))
                window.wizard.reject()
            saved = window.grab().save(str(args.output / "today.png"))
            window.navigation.setCurrentRow(5)
            app.processEvents()
            saved = window.grab().save(str(args.output / "settings.png")) and saved
            outcome.update(ok=saved, error="" if saved else "Screenshot failed")
            timer.stop()
            window.close()
            app.quit()

        timer = QTimer()
        timer.timeout.connect(capture)
        timer.start(100)
        QTimer.singleShot(15000, app.quit)
        app.exec()
        window.pool.waitForDone(6000)
    (args.output / "smoke.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(json.dumps(outcome))
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
