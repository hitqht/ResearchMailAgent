import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import QWizard
from pytestqt.qtbot import QtBot

from researchmail.config import AppPaths
from researchmail.gui.window import NAVIGATION, MainWindow
from researchmail.gui.worker import Worker
from researchmail.services.workspace import WorkspaceService


def wait_idle(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.waitUntil(
        lambda: (
            not window.jobs
            and not window.mail_controller.jobs
            and not window.ai_controller.jobs
            and not window.draft_controller.jobs
        ),
        timeout=10000,
    )


def test_start_navigation_onboarding_and_persistence(qtbot: QtBot, paths: AppPaths) -> None:
    service = WorkspaceService(paths)
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.wizard is not None)
    wizard = window.wizard
    assert wizard is not None
    assert wizard.currentId() == 0
    assert wizard.button(QWizard.WizardButton.CancelButton).isVisible()
    qtbot.mouseClick(wizard.button(QWizard.WizardButton.NextButton), Qt.MouseButton.LeftButton)
    assert wizard.currentId() == 1
    qtbot.mouseClick(wizard.button(QWizard.WizardButton.NextButton), Qt.MouseButton.LeftButton)
    qtbot.mouseClick(wizard.button(QWizard.WizardButton.FinishButton), Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: service.initialize().onboarding_completed)
    wait_idle(qtbot, window)
    for row, name in enumerate(NAVIGATION):
        window.navigation.setCurrentRow(row)
        assert window.pages.currentIndex() == row
        assert window.navigation.currentItem().text() == name
    assert "WAL" in window.storage_status.text()
    assert window.backup_button.isEnabled()
    window.close()


def test_cancel_onboarding_reappears(qtbot: QtBot, service: WorkspaceService) -> None:
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.wizard is not None)
    window.wizard.reject()
    assert not service.initialize().onboarding_completed
    window.show_onboarding()
    assert window.wizard is not None
    window.wizard.reject()
    wait_idle(qtbot, window)


def test_backup_feedback_and_restart(qtbot: QtBot, service: WorkspaceService) -> None:
    service.complete_onboarding()
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.ready)
    assert window.wizard is None
    window.navigation.setCurrentRow(5)
    qtbot.mouseClick(window.backup_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "备份已保存" in window.backup_status.text())
    wait_idle(qtbot, window)
    assert list((service.paths.data / "backups").glob("*.sqlite3"))


def test_storage_error_has_no_traceback(qtbot: QtBot, paths: AppPaths) -> None:
    paths.database.write_bytes(b"corrupt fixture")
    window = MainWindow(WorkspaceService(paths))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: "原文件已保留" in window.storage_status.text())
    wait_idle(qtbot, window)
    assert not window.ready
    assert not window.backup_button.isEnabled()
    assert "Traceback" not in window.storage_status.text()
    assert paths.database.read_bytes() == b"corrupt fixture"


def test_backup_error_is_safe(
    qtbot: QtBot, service: WorkspaceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.complete_onboarding()
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.ready)

    def broken() -> Path:
        raise OSError("private mail body fixture")

    monkeypatch.setattr(service, "backup", broken)
    window.backup()
    qtbot.waitUntil(lambda: "备份未完成" in window.backup_status.text())
    wait_idle(qtbot, window)
    assert "private mail" not in window.backup_status.text()
    assert window.backup_button.isEnabled()


def test_worker_does_not_block_event_loop(qtbot: QtBot) -> None:
    def slow() -> str:
        time.sleep(0.15)
        return "done"

    worker = Worker(slow)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    with qtbot.waitSignal(worker.signals.succeeded, timeout=3000) as result:
        QThreadPool.globalInstance().start(worker)
    timer.stop()
    assert result.args == ["done"]
    assert len(ticks) >= 2


def test_worker_failure_is_sanitized(qtbot: QtBot) -> None:
    def broken() -> None:
        raise RuntimeError("sensitive fixture")

    worker = Worker(broken)
    with qtbot.waitSignal(worker.signals.failed, timeout=3000) as result:
        QThreadPool.globalInstance().start(worker)
    assert result.args == []
