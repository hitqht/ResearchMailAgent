"""Explicit standalone self-test: temporary synthetic data, no network or Keychain access."""

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QScrollArea

from researchmail.config import AppPaths
from researchmail.drafts.models import DraftContent
from researchmail.gui.window import MainWindow
from researchmail.llm.models import ModelConfig
from researchmail.llm.providers import MockProvider
from researchmail.mail.models import AccountConfig, Folder, ParsedMessage
from researchmail.services.ai_service import AIService
from researchmail.services.workspace import WorkspaceService
from researchmail.storage.draft_repository import DraftRepository
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
        mock = MockProvider(
            json.dumps(
                {
                    "category": "revision",
                    "priority": "normal",
                    "confidentiality": "sensitive",
                    "summary": "这是一封本机界面测试邮件，提醒核对修改说明。",
                    "evidence": ["所有内容均为合成数据。"],
                    "confidence": 0.8,
                    "tasks": [
                        {
                            "title": "核对修改说明（合成任务）",
                            "deadline": None,
                            "deadline_kind": "revision",
                            "evidence": "所有内容均为合成数据。",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        ai = AIService(service.database, factory=lambda config, secret: mock)
        model = ai.save_model(
            ModelConfig(
                label="本机模型（合成配置）",
                provider="ollama",
                model="synthetic-only",
                base_url="http://127.0.0.1:11434",
            ),
            "",
        )
        ai.analyze(1, model)
        ai.repository.update_task(ai.repository.tasks()[0].id, "confirmed")
        DraftRepository(service.database).create(
            DraftContent(
                account_id=account,
                message_id=1,
                recipients=("editor@example.invalid",),
                subject="Re: 论文修改说明（合成草稿）",
                body="编辑您好：\n\n这是一封仅供界面测试的合成草稿。\n请人工核对内容后再审批。",
            )
        )
        window = MainWindow(service, ai_service=ai)
        window.show()

        plan = [
            (0, "today"),
            (1, "mail"),
            (2, "analysis"),
            (3, "tasks"),
            (4, "drafts"),
            (5, "settings"),
            (5, "settings-models"),
        ]
        cursor = 0
        saved = True

        def capture() -> None:
            nonlocal cursor, saved
            if (
                not window.ready
                or window.jobs
                or window.mail_controller.jobs
                or window.ai_controller.jobs
                or window.draft_controller.jobs
            ):
                return
            if window.wizard is not None:
                window.wizard.grab().save(str(output / "onboarding.png"))
                window.wizard.reject()
            if cursor < len(plan):
                row, name = plan[cursor]
                window.navigation.setCurrentRow(row)
                if window.draft_controller.jobs:
                    return
                if name == "mail":
                    window.mail_browser.messages.setCurrentRow(0)
                if name == "settings-models":
                    settings = window.pages.widget(5)
                    if isinstance(settings, QScrollArea):
                        settings.ensureWidgetVisible(window.model_editor)
                app.processEvents()
                saved = window.grab().save(str(output / (name + ".png"))) and saved
                cursor += 1
                return
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
