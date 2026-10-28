from pydantic import ValidationError
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from researchmail.drafts.models import ERRORS, Draft, DraftContent, DraftStatus
from researchmail.gui.ai_controller import AIController, AISnapshot
from researchmail.gui.ai_widgets import label
from researchmail.gui.draft_controller import DraftController, DraftSnapshot, PreviewAction
from researchmail.gui.mail_controller import MailboxSnapshot, MailController

STATUS = {
    DraftStatus.DRAFT: "待编辑",
    DraftStatus.REVIEWED: "已审核",
    DraftStatus.APPROVED: "已批准",
    DraftStatus.SENDING: "发送中",
    DraftStatus.SENT: "服务器已接受",
    DraftStatus.UNCERTAIN: "结果待核实",
    DraftStatus.FAILED: "发送失败",
}


class DraftPanel(QWidget):
    def __init__(self, controller: DraftController, mail: MailController, ai: AIController) -> None:
        super().__init__()
        self.controller = controller
        self.draft: Draft | None = None
        self.dirty = False
        self.loading = False
        self.busy = False
        layout = QVBoxLayout(self)
        layout.addWidget(
            label("保存后依次审核、批准，再确认发送。修改后审批失效；结果待核实禁止重发。")
        )
        source = QHBoxLayout()
        self.messages = QComboBox()
        self.models = QComboBox()
        self.messages.setAccessibleName("回复来源邮件")
        self.models.setAccessibleName("草稿本地模型")
        source.addWidget(self.messages, 1)
        source.addWidget(self.models, 1)
        self.refresh = QPushButton("刷新草稿")
        self.refresh.clicked.connect(controller.refresh)
        source.addWidget(self.refresh)
        layout.addLayout(source)
        self.intent = QLineEdit()
        self.intent.setPlaceholderText("填写本次回复意图；本地模型仅生成待审核正文")
        self.intent.setAccessibleName("回复意图")
        layout.addWidget(self.intent)
        row = QHBoxLayout()
        self.new = QPushButton("新建空白草稿")
        self.reply = QPushButton("按意图创建回复")
        self.generate = QPushButton("本地模型生成回复")
        for new_button in (self.new, self.reply, self.generate):
            row.addWidget(new_button)
        layout.addLayout(row)
        split = QSplitter()
        self.list = QListWidget()
        self.list.setAccessibleName("本地草稿列表")
        split.addWidget(self.list)
        editor = QWidget()
        form_layout = QVBoxLayout(editor)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.account = QComboBox()
        self.recipients = QLineEdit()
        self.subject = QLineEdit()
        self.recipients.setPlaceholderText("多个收件邮箱用逗号分隔；不支持抄送或附件")
        for name, widget in (
            ("发件账户", self.account),
            ("收件人", self.recipients),
            ("主题", self.subject),
        ):
            widget.setAccessibleName(name)
            form.addRow(name, widget)
        form_layout.addLayout(form)
        self.body = QPlainTextEdit()
        self.body.setAccessibleName("草稿正文")
        form_layout.addWidget(self.body, 1)
        self.save = QPushButton("保存当前草稿")
        save_row = QHBoxLayout()
        save_row.addWidget(self.save)
        self.discard = QPushButton("撤销未保存修改")
        self.discard.clicked.connect(lambda: self._select(self.list.currentRow()))
        save_row.addWidget(self.discard)
        form_layout.addLayout(save_row)
        split.addWidget(editor)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        actions = QHBoxLayout()
        self.review = QPushButton("核对并标记审核")
        self.approve = QPushButton("批准当前版本")
        self.send = QPushButton("发送已批准版本")
        self.reopen = QPushButton("失败后重新审核")
        for button in (self.review, self.approve, self.send, self.reopen):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.feedback = label("尚无草稿。创建或生成不会发信。SMTP成功仅表示服务器接受。")
        layout.addWidget(self.feedback)
        self.list.currentRowChanged.connect(self._select)
        for field in (self.recipients, self.subject):
            field.textChanged.connect(self._edited)
        self.body.textChanged.connect(self._edited)
        self.account.currentIndexChanged.connect(self._edited)
        self.new.clicked.connect(
            lambda: controller.create(
                DraftContent(
                    account_id=self.account.currentData(), recipients=(), subject="", body=""
                )
            )
        )
        self.reply.clicked.connect(lambda: self._reply(False))
        self.generate.clicked.connect(lambda: self._reply(True))
        self.save.clicked.connect(self._save)
        self.review.clicked.connect(lambda: self._preview("review"))
        self.approve.clicked.connect(lambda: self._preview("approve"))
        self.send.clicked.connect(lambda: self._preview("send"))
        self.reopen.clicked.connect(self._reopen)
        controller.changed.connect(self.apply_snapshot)
        controller.status.connect(self.feedback.setText)
        controller.busy.connect(self._busy)
        controller.preview_ready.connect(self._dialog)
        mail.changed.connect(self._mail)
        ai.changed.connect(self._models)
        self._buttons()

    @Slot(object)
    def _mail(self, value: object) -> None:
        if not isinstance(value, MailboxSnapshot):
            return
        account = self.account.currentData()
        message = self.messages.currentData()
        self.loading = True
        self.account.clear()
        self.account.addItem("请选择发件账户", None)
        for a in value.accounts:
            self.account.addItem(a.config.email, a.id)
        self.account.setCurrentIndex(max(0, self.account.findData(account)))
        self.messages.clear()
        for m in value.messages:
            self.messages.addItem(m.parsed.subject or "（无主题）", m.id)
        self.messages.setCurrentIndex(max(0, self.messages.findData(message)))
        self.loading = False

    @Slot(object)
    def _models(self, value: object) -> None:
        if not isinstance(value, AISnapshot):
            return
        selected = self.models.currentData()
        self.models.clear()
        self.models.addItem("本地优先自动选择", None)
        for model in value.models:
            if model.config.local:
                self.models.addItem(model.config.label, model.id)
        self.models.setCurrentIndex(max(0, self.models.findData(selected)))

    @Slot(object)
    def apply_snapshot(self, value: object) -> None:
        if not isinstance(value, DraftSnapshot):
            return
        self.loading = True
        self.list.clear()
        for draft in value.drafts:
            self.list.addItem(
                f"#{draft.id} · {STATUS[draft.status]} · 版本 {draft.revision}\n"
                f"{draft.content.subject or '（无主题）'}"
            )
        index = next((i for i, d in enumerate(value.drafts) if d.id == value.selected_id), 0)
        self.loading = False
        self.list.setCurrentRow(index if value.drafts else -1)
        self._select(self.list.currentRow())

    @Slot(int)
    def _select(self, index: int) -> None:
        if self.loading:
            return
        drafts = self.controller.state.drafts
        self.loading = True
        self.draft = drafts[index] if 0 <= index < len(drafts) else None
        self.controller.state = DraftSnapshot(drafts, self.draft.id if self.draft else None)
        content = self.draft.content if self.draft else None
        self.account.setCurrentIndex(
            max(0, self.account.findData(content.account_id if content else None))
        )
        self.recipients.setText(", ".join(content.recipients) if content else "")
        self.subject.setText(content.subject if content else "")
        self.body.setPlainText(content.body if content else "")
        self.dirty = False
        self.loading = False
        self._buttons()
        if self.draft and self.draft.last_error:
            self.feedback.setText(ERRORS.get(self.draft.last_error, ERRORS["storage"]))

    @Slot()
    def _edited(self) -> None:
        if not self.loading:
            self.dirty = True
            self._buttons()
            self.feedback.setText("有未保存的修改。保存后需重新审核与批准。")

    def _content(self) -> DraftContent:
        return DraftContent(
            account_id=self.account.currentData(),
            message_id=self.draft.content.message_id if self.draft else None,
            recipients=tuple(v.strip() for v in self.recipients.text().split(",") if v.strip()),
            subject=self.subject.text(),
            body=self.body.toPlainText(),
        )

    @Slot()
    def _save(self) -> None:
        if self.draft is None:
            return
        try:
            content = self._content()
        except ValidationError:
            self.feedback.setText(ERRORS["config"])
            return
        self.controller.save(self.draft, content)

    def _reply(self, use_model: bool) -> None:
        message = self.messages.currentData()
        if message is not None:
            self.controller.reply(message, self.intent.text(), self.models.currentData(), use_model)

    def _preview(self, action: str) -> None:
        if self.draft and not self.dirty:
            try:
                if self._content() != self.draft.content:
                    self._edited()
                    return
            except ValidationError:
                self.feedback.setText(ERRORS["config"])
                return
            self.controller.preview(self.draft.id, action)

    @Slot()
    def _reopen(self) -> None:
        if self.draft:
            self.controller.reopen(self.draft.id)

    @Slot(object)
    def _dialog(self, value: object) -> None:
        if not isinstance(value, PreviewAction):
            return
        preview = value.preview
        c = preview.draft.content
        dialog = QDialog(self)
        dialog.setWindowTitle("核对当前草稿")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            label(
                f"草稿 #{preview.draft.id} · 版本 {preview.draft.revision}\n"
                f"发件人：{preview.account.config.email}\n收件人：{', '.join(c.recipients)}\n"
                f"SMTP SSL：{preview.account.config.smtp_host}:{preview.account.config.smtp_port}\n"
                f"主题：{c.subject}"
            )
        )
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(c.body)
        layout.addWidget(body, 1)
        layout.addWidget(
            label(
                "SMTP接受后不等于最终送达。提交后若超时或中断，请核实结果后再处理。"
                if value.action == "send"
                else "请核对收件人、内容和发件账户。后续修改将使本次审核或审批失效。"
            )
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        names = {
            "review": "已核对，标记审核",
            "approve": "批准这个版本",
            "send": "立即发送这封邮件",
        }
        accept = buttons.addButton(names[value.action], QDialogButtonBox.ButtonRole.AcceptRole)
        accept.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.rejected.connect(dialog.reject)
        accept.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.confirm(value)

    @Slot(bool)
    def _busy(self, busy: bool) -> None:
        self.busy = busy
        self._buttons()

    def _buttons(self) -> None:
        d = self.draft
        ready = bool(d and not self.dirty and not self.busy)
        editable = bool(
            d and d.status not in {DraftStatus.SENDING, DraftStatus.SENT, DraftStatus.UNCERTAIN}
        )
        for widget in (self.account, self.recipients, self.subject, self.body):
            widget.setEnabled(editable and not self.busy)
        self.list.setEnabled(not self.busy and not self.dirty)
        self.save.setEnabled(editable and not self.busy)
        self.discard.setEnabled(self.dirty and not self.busy)
        for button in (self.new, self.reply, self.generate, self.refresh):
            button.setEnabled(not self.busy and not self.dirty)
        self.review.setEnabled(bool(ready and d and d.status == DraftStatus.DRAFT))
        self.approve.setEnabled(bool(ready and d and d.status == DraftStatus.REVIEWED))
        self.send.setEnabled(bool(ready and d and d.status == DraftStatus.APPROVED))
        self.reopen.setEnabled(bool(ready and d and d.status == DraftStatus.FAILED))
