import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from researchmail.gui.window import MainWindow
from researchmail.mail.models import Failure, MailError
from researchmail.services.mail_service import MailService
from tests.fakes import FakeSession, MemoryVault
from tests.test_gui import wait_idle


def window_with_mail(qtbot, service):
    service.complete_onboarding()
    vault = MemoryVault()
    session = FakeSession()
    mail = MailService(service.database, vault, lambda config, secret: session, lambda _: None)
    window = MainWindow(service, mail_service=mail)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.ready)
    wait_idle(qtbot, window)
    return window, vault, session


def save_account(qtbot, window):
    window.navigation.setCurrentRow(5)
    editor = window.account_editor
    editor.email.setText("fixture@example.invalid")
    editor.secret.setText("synthetic-only")
    qtbot.mouseClick(editor.save, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert len(window.mail_controller.state.accounts) == 1
    assert editor.secret.text() == ""


def test_add_test_sync_search_plain_detail_and_model_independence(qtbot, service) -> None:
    window, vault, session = window_with_mail(qtbot, service)
    save_account(qtbot, window)
    qtbot.mouseClick(window.account_editor.test, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert "只读连接成功" in window.account_editor.feedback.text()
    window.navigation.setCurrentRow(1)
    browser = window.mail_browser
    assert browser.folder.count() == 2
    qtbot.mouseClick(browser.sync, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert browser.messages.count() == 2
    browser.messages.setCurrentRow(0)
    assert "Please revise" in browser.detail.toPlainText()
    browser.search.setText("submission")
    QTest.keyClick(browser.search, Qt.Key.Key_Return)
    wait_idle(qtbot, window)
    assert browser.messages.count() == 1
    assert len(session.fetched) == 2
    browser.messages.setCurrentRow(0)
    assert "Synthetic submission" in browser.detail.toPlainText()
    window.close()


def test_invalid_config_error_feedback_and_switching(qtbot, service) -> None:
    window, vault, session = window_with_mail(qtbot, service)
    editor = window.account_editor
    window.navigation.setCurrentRow(5)
    qtbot.mouseClick(editor.save, Qt.MouseButton.LeftButton)
    assert "配置不完整" in editor.feedback.text()
    save_account(qtbot, window)

    def denied(config, secret):
        raise MailError(Failure.AUTH)

    window.mail_controller.service.factory = denied
    qtbot.mouseClick(editor.test, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert "认证失败" in editor.feedback.text()
    assert "Traceback" not in editor.feedback.text()
    assert editor.isEnabled()
    editor.selector.setCurrentIndex(editor.selector.count() - 1)
    assert editor.email.text() == ""
    assert editor.account_id is None


def test_timer_opt_in_and_stop_sync(qtbot, service, monkeypatch) -> None:
    window, vault, session = window_with_mail(qtbot, service)
    save_account(qtbot, window)
    assert not window.mail_controller.timer.isActive()
    editor = window.account_editor
    editor.interval.setValue(5)
    qtbot.mouseClick(editor.save, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert window.mail_controller.timer.isActive()
    session.content = {i: b"Subject: test\r\n\r\nfixture" for i in range(1, 21)}
    original = session.fetch

    def slow(uid):
        time.sleep(0.02)
        return original(uid)

    monkeypatch.setattr(session, "fetch", slow)
    window.navigation.setCurrentRow(1)
    window.mail_controller.timer.timeout.emit()
    qtbot.waitUntil(lambda: len(session.fetched) > 0)
    qtbot.mouseClick(window.mail_browser.stop, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert "已停止" in window.mail_browser.feedback.text()
    assert len(session.fetched) < 20
    assert window.mail_browser.sync.isEnabled()
