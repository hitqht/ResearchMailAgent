import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from researchmail.drafts.models import DraftStatus
from researchmail.gui.window import MainWindow
from tests.test_drafts import create
from tests.test_gui import wait_idle


def window(qtbot, service, ai, drafts):
    service.complete_onboarding()
    create(drafts)
    result = MainWindow(service, ai_service=ai[0], draft_service=drafts)
    qtbot.addWidget(result)
    result.show()
    qtbot.waitUntil(lambda: result.ready)
    wait_idle(qtbot, result)
    result.navigation.setCurrentRow(4)
    wait_idle(qtbot, result)
    return result


def act(qtbot, w, button, accept=True):
    panel = w.draft_panel
    observed = []
    assert button.isEnabled()
    timer = QTimer(panel)

    def dialog():
        active = [d for d in panel.findChildren(QDialog) if d.isVisible()]
        if not active:
            return
        timer.stop()
        box = active[0].findChild(QDialogButtonBox)
        assert box.button(QDialogButtonBox.StandardButton.Cancel).isDefault()
        observed.append(True)
        if accept:
            active[0].accept()
        else:
            active[0].reject()

    timer.timeout.connect(dialog)
    timer.start(10)
    try:
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: bool(observed))
        wait_idle(qtbot, w)
    finally:
        timer.stop()


def test_review_approve_cancel_send_then_send(qtbot, service, ai, drafts):
    w = window(qtbot, service, ai, drafts)
    p = w.draft_panel
    assert p.review.isEnabled() and not p.approve.isEnabled() and not p.send.isEnabled()
    act(qtbot, w, p.review)
    assert p.approve.isEnabled() and not drafts.transport.sent
    act(qtbot, w, p.approve)
    assert p.send.isEnabled() and not drafts.transport.sent
    act(qtbot, w, p.send, False)
    assert p.send.isEnabled() and not drafts.transport.sent
    act(qtbot, w, p.send)
    assert len(drafts.transport.sent) == 1
    assert p.draft.status == DraftStatus.SENT and not p.send.isEnabled() and not p.body.isEnabled()


def test_edit_after_approval_requires_save_and_reapproval(qtbot, service, ai, drafts):
    w = window(qtbot, service, ai, drafts)
    p = w.draft_panel
    act(qtbot, w, p.review)
    act(qtbot, w, p.approve)
    p.body.setPlainText("Changed body")
    assert p.dirty and not p.send.isEnabled() and not p.new.isEnabled() and not p.list.isEnabled()
    qtbot.mouseClick(p.save, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, w)
    assert p.draft.status == DraftStatus.DRAFT and p.review.isEnabled() and not p.send.isEnabled()


def test_timeout_visible_locked_and_recovered(qtbot, service, ai, drafts):
    w = window(qtbot, service, ai, drafts)
    p = w.draft_panel
    act(qtbot, w, p.review)
    act(qtbot, w, p.approve)
    drafts.transport.error = TimeoutError("private response")
    act(qtbot, w, p.send)
    assert p.draft.status == DraftStatus.UNCERTAIN
    assert "待核实" in p.feedback.text() and "private" not in p.feedback.text()
    assert not p.send.isEnabled() and not p.reopen.isEnabled()


def test_create_reply_and_model_generation_only_local(qtbot, service, ai, drafts):
    w = window(qtbot, service, ai, drafts)
    p = w.draft_panel
    ai[1].response = json.dumps({"subject": "Re: Synthetic", "body": "请澄清修改要求。"})
    p.intent.setText("询问修改要求")
    qtbot.mouseClick(p.generate, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, w)
    assert p.body.toPlainText() == "请澄清修改要求。"
    assert not drafts.transport.sent and p.draft.status == DraftStatus.DRAFT
    qtbot.mouseClick(p.new, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, w)
    assert not p.body.toPlainText()
    p.recipients.setText("invalid")
    qtbot.mouseClick(p.save, Qt.MouseButton.LeftButton)
    assert "有效的收件邮箱" in p.feedback.text()


def test_unsaved_changes_survive_close_and_can_be_discarded(qtbot, service, ai, drafts):
    w = window(qtbot, service, ai, drafts)
    p = w.draft_panel
    original = p.body.toPlainText()
    p.body.setPlainText("Unsaved synthetic edit")
    w.close()
    assert w.isVisible() and p.body.toPlainText() == "Unsaved synthetic edit"
    qtbot.mouseClick(p.discard, Qt.MouseButton.LeftButton)
    assert not p.dirty and p.body.toPlainText() == original


def test_smtp_test_feedback_no_send(qtbot, service, ai, drafts, monkeypatch):
    w = window(qtbot, service, ai, drafts)
    observed = []
    monkeypatch.setattr(drafts, "test_smtp", lambda account: observed.append(account))
    w.draft_controller.test_smtp(1)
    wait_idle(qtbot, w)
    assert observed == [1] and "SMTP SSL 认证成功" in w.draft_panel.feedback.text()
    assert not drafts.transport.sent
