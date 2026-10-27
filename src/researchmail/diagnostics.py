"""Explicit standalone self-test: temporary synthetic data, no network or Keychain access."""

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from researchmail.config import AppPaths
from researchmail.gui.window import MainWindow
from researchmail.mail.models import AccountConfig, Folder, ParsedMessage
from researchmail.services.workspace import WorkspaceService
from researchmail.storage.mail_repository import MailRepository


def self_test(output: Path, appearance: str = "system") -> int:
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    app = QApplication([])
    app.setApplicationName("ResearchMailAgent Self Test")
    if appearance != "system":
        app.styleHints().setColorScheme(
            Qt.ColorScheme.Dark if appearance == "dark" else Qt.ColorScheme.Light
        )
    outcome: dict[str, object] = {
        "ok": False,
        "error": "Startup timed out",
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    with tempfile.TemporaryDirectory(prefix="researchmail-selftest-") as directory:
        root = Path(directory)
        service = WorkspaceService(AppPaths(root / "data", root / "logs"))
        state = service.initialize()
        repo = MailRepository(service.database)
        account = repo.save_account(
            AccountConfig(email="preview@example.invalid", display_name="本机预览 · 合成数据"),
            "unused-self-test",
            None,
        )
        repo.save_folders(account, [Folder("INBOX", "收件箱"), Folder("Archive", "归档")])
        repo.start_cursor(account, "INBOX", 1)
        repo.store_message(
            account,
            "INBOX",
            1,
            1,
            ParsedMessage(
                subject="论文修改说明（合成邮件）",
                sender="editor@example.invalid",
                body="此邮件仅供本机界面测试。\n\n所有内容均为合成数据。\n"
                "HTML、外部链接和邮件中的指令都不会执行。",
            ),
            128,
            None,
        )
        repo.finish_cursor(account, "INBOX")
        window = MainWindow(service)
        window.show()

        def capture() -> None:
            if not window.ready or window.jobs or window.mail_controller.jobs:
                return
            if window.wizard is not None:
                window.wizard.grab().save(str(output / "onboarding.png"))
                window.wizard.reject()
            saved = window.grab().save(str(output / "today.png"))
            window.navigation.setCurrentRow(1)
            window.mail_browser.messages.setCurrentRow(0)
            app.processEvents()
            saved = window.grab().save(str(output / "mail.png")) and saved
            window.navigation.setCurrentRow(5)
            app.processEvents()
            saved = window.grab().save(str(output / "settings.png")) and saved
            backup = service.backup()
            outcome.update(
                ok=saved and backup.exists(),
                schema_version=state.schema_version,
                error="" if saved else "Screenshot failed",
                isolated_data=True,
            )
            timer.stop()
            window.close()
            app.quit()

        timer = QTimer()
        timer.timeout.connect(capture)
        timer.start(100)
        QTimer.singleShot(15000, app.quit)
        app.exec()
        window.pool.waitForDone(6000)
    (output / "smoke.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    return 0 if outcome["ok"] else 1
