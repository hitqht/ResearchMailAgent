from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from researchmail.gui.ai_controller import CloudPreview
from researchmail.gui.window import MainWindow
from researchmail.llm.models import AIError, Preferences
from tests.test_gui import wait_idle


def ai_window(qtbot, service, ai):
    ai_service, mock, vault, local, cloud = ai
    service.complete_onboarding()
    window = MainWindow(service, ai_service=ai_service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.ready)
    wait_idle(qtbot, window)
    return window


def test_model_switch_keychain_test_and_safe_error(qtbot, service, ai):
    window = ai_window(qtbot, service, ai)
    editor = window.model_editor
    window.navigation.setCurrentRow(5)
    editor.selection.setCurrentIndex(editor.selection.findData(ai[4]))
    assert editor.provider.currentData() == "openai_compatible"
    assert editor.secret.text() == ""
    editor.secret.setText("replacement-synthetic")
    qtbot.mouseClick(editor.save, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert editor.secret.text() == ""
    assert "replacement-synthetic" in ai[2].values.values()
    editor.default.setCurrentIndex(editor.default.findData(ai[4]))
    editor.local_first.setChecked(False)
    editor.reminders.setChecked(True)
    qtbot.mouseClick(editor.save_prefs, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert ai[0].repository.preferences() == Preferences(
        default_model_id=ai[4], local_first=False, reminders=True
    )
    ai[1].response = '{"ok":true}'
    qtbot.mouseClick(editor.test, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)

    def unavailable(config, secret):
        raise AIError("network")

    ai[0].factory = unavailable
    qtbot.mouseClick(editor.test, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert "无法连接模型" in editor.feedback.text()
    assert "Traceback" not in editor.feedback.text()


def test_analysis_task_confirmation_date_and_reminder(qtbot, service, ai):
    window = ai_window(qtbot, service, ai)
    window.navigation.setCurrentRow(2)
    panel = window.analysis_panel
    assert panel.messages.count() == 1
    qtbot.mouseClick(panel.analyze, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert "请修改论文" in panel.detail.toPlainText()
    assert window.task_panel.list.count() == 1
    window.navigation.setCurrentRow(3)
    tasks = window.task_panel
    tasks.deadline.setText("not-a-date")
    qtbot.mouseClick(tasks.confirm, Qt.MouseButton.LeftButton)
    assert "有效日期" in tasks.feedback.text()
    tasks.deadline.setText(date.today().isoformat())
    ai[0].repository.save_preferences(Preferences(reminders=True))
    qtbot.mouseClick(tasks.confirm, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert ai[0].repository.tasks()[0].status == "confirmed"
    assert "提交修改稿" in window.daily_digest.toPlainText()
    assert "截止提醒" in window.reminder_label.text()
    assert len(window.ai_controller._reminded) == 1
    window.ai_controller.check_reminders()
    assert len(window.ai_controller._reminded) == 1
    qtbot.mouseClick(tasks.done, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert ai[0].repository.tasks()[0].status == "done"
    assert "提交修改稿" not in window.daily_digest.toPlainText()


def test_cloud_preview_cancel_and_explicit_approval(qtbot, service, ai):
    window = ai_window(qtbot, service, ai)
    window.navigation.setCurrentRow(2)
    panel = window.analysis_panel
    panel.models.setCurrentIndex(panel.models.findData(ai[4]))
    observed = []

    def cancel():
        dialog = panel.findChild(QDialog)
        if dialog is None:
            QTimer.singleShot(10, cancel)
            return
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault()
        observed.append(dialog.windowTitle())
        dialog.reject()

    QTimer.singleShot(10, cancel)
    qtbot.mouseClick(panel.analyze, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(observed))
    wait_idle(qtbot, window)
    assert ai[1].calls == 0

    def approve():
        dialogs = [d for d in panel.findChildren(QDialog) if d.isVisible()]
        if not dialogs:
            QTimer.singleShot(10, approve)
            return
        buttons = dialogs[0].findChild(QDialogButtonBox)
        button = next(b for b in buttons.buttons() if "授权发送" in b.text())
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(10, approve)
    qtbot.mouseClick(panel.analyze, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: ai[1].calls == 1)
    wait_idle(qtbot, window)
    assert len(ai[0].repository.analyses()) == 1


def test_preview_content_change_denied(qtbot, service, ai):
    window = ai_window(qtbot, service, ai)
    model = ai[0].repository.model(ai[4])
    preview = CloudPreview(1, model, "outdated preview")
    window.ai_controller.approve(preview)
    wait_idle(qtbot, window)
    assert ai[1].calls == 0
    assert "云端处理已阻止" in window.model_editor.feedback.text()


def test_new_model_form_validation_and_local_save(qtbot, service, ai):
    window = ai_window(qtbot, service, ai)
    window.navigation.setCurrentRow(5)
    editor = window.model_editor
    qtbot.mouseClick(editor.save, Qt.MouseButton.LeftButton)
    assert "模型配置无效" in editor.feedback.text()
    editor.name.setText("Second Local")
    editor.model.setText("synthetic-v2")
    qtbot.mouseClick(editor.save, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert len(ai[0].repository.models()) == 3
    editor.selection.setCurrentIndex(editor.selection.count() - 1)
    assert editor.model.text() == "synthetic-v2"
    assert editor.auth.currentData() == "none"
