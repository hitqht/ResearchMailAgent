import json
from datetime import date

from pydantic import ValidationError
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from researchmail.gui.ai_controller import AIController, AISnapshot, CloudPreview
from researchmail.gui.mail_controller import MailboxSnapshot, MailController
from researchmail.llm.models import ERRORS, Analysis, ModelConfig, Preferences

CATEGORY_LABELS = {
    "submission": "论文投稿",
    "revision": "退修 / 校样",
    "review_invitation": "审稿邀请",
    "review_assignment": "审稿任务",
    "collaboration": "科研合作",
    "institutional_notice": "机构通知",
    "other": "其他",
}
PRIORITY_LABELS = {"high": "高", "normal": "普通", "low": "低"}
CONFIDENTIALITY_LABELS = {"unknown": "未知（按敏感处理）", "sensitive": "敏感", "public": "公开"}
STATUS_LABELS = {
    "suggested": "待确认",
    "confirmed": "已确认",
    "done": "已完成",
    "dismissed": "已忽略",
}
KIND_LABELS = {
    "invitation_response": "邀请回复",
    "review_report": "审稿报告",
    "revision": "退修",
    "proof": "校样",
    "other": "其他",
}


def label(text: str) -> QLabel:
    result = QLabel(text)
    result.setWordWrap(True)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


class ModelEditor(QWidget):
    def __init__(self, controller: AIController) -> None:
        super().__init__()
        self.controller = controller
        self.state = controller.state
        layout = QVBoxLayout(self)
        layout.addWidget(label("模型与认证"))
        self.selection = QComboBox()
        layout.addWidget(self.selection)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name = QLineEdit()
        self.provider = QComboBox()
        self.provider.addItem("Ollama · 本机", "ollama")
        self.provider.addItem("OpenAI 兼容 · 云端", "openai_compatible")
        self.model = QLineEdit()
        self.url = QLineEdit("http://127.0.0.1:11434")
        self.auth = QComboBox()
        self.auth.addItem("无认证", "none")
        self.auth.addItem("Bearer API Key", "bearer")
        self.auth.addItem("x-api-key", "x-api-key")
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("保存到 Keychain；留空保留已保存凭据")
        for text, widget in (
            ("配置名称", self.name),
            ("提供商", self.provider),
            ("模型名称", self.model),
            ("Base URL", self.url),
            ("认证方式", self.auth),
            ("API Key", self.secret),
        ):
            widget.setAccessibleName(text)
            form.addRow(text, widget)
        layout.addLayout(form)
        layout.addWidget(
            label(
                "Ollama 使用本机 IP（127.0.0.1 或 ::1）；云端填写 HTTPS Base URL"
                "（通常以 /v1 结尾）。只支持所列 API 认证方式。"
            )
        )
        row = QHBoxLayout()
        self.save = QPushButton("保存模型")
        self.test = QPushButton("测试已保存模型")
        row.addWidget(self.save)
        row.addWidget(self.test)
        layout.addLayout(row)
        self.default = QComboBox()
        self.local_first = QCheckBox("本地优先；本地模型失败后由我决定下一步")
        self.reminders = QCheckBox("启用应用内截止提醒（应用运行期间）")
        self.days = QSpinBox()
        self.days.setRange(0, 30)
        self.days.setSuffix(" 天内")
        form2 = QFormLayout()
        form2.addRow("默认模型", self.default)
        form2.addRow(self.local_first)
        form2.addRow(self.reminders)
        form2.addRow("提醒范围", self.days)
        layout.addLayout(form2)
        self.save_prefs = QPushButton("保存模型与提醒偏好")
        layout.addWidget(self.save_prefs)
        self.feedback = label("API Key 仅存 macOS Keychain；连接测试不会发送邮件内容。")
        layout.addWidget(self.feedback)
        self.selection.currentIndexChanged.connect(self._select)
        self.provider.currentIndexChanged.connect(self._provider)
        self.save.clicked.connect(self._save)
        self.test.clicked.connect(self._test)
        self.save_prefs.clicked.connect(self._prefs)
        controller.changed.connect(self.apply_snapshot)
        controller.status.connect(self.feedback.setText)
        controller.busy.connect(self._busy)

    @Slot(object)
    def apply_snapshot(self, value: object) -> None:
        if not isinstance(value, AISnapshot):
            return
        selected = self.selection.currentData()
        self.state = value
        self.selection.blockSignals(True)
        self.selection.clear()
        self.selection.addItem("新建模型", None)
        self.default.clear()
        self.default.addItem("未选择", None)
        for model in value.models:
            self.selection.addItem(model.config.label, model.id)
            self.default.addItem(model.config.label, model.id)
        self.selection.setCurrentIndex(max(0, self.selection.findData(selected)))
        self.selection.blockSignals(False)
        self.default.setCurrentIndex(
            max(0, self.default.findData(value.preferences.default_model_id))
        )
        self.local_first.setChecked(value.preferences.local_first)
        self.reminders.setChecked(value.preferences.reminders)
        self.days.setValue(value.preferences.reminder_days)
        self._select()

    @Slot()
    def _select(self) -> None:
        saved = next((m for m in self.state.models if m.id == self.selection.currentData()), None)
        self.secret.clear()
        self.name.setText(saved.config.label if saved else "")
        self.model.setText(saved.config.model if saved else "")
        self.provider.setCurrentIndex(
            self.provider.findData(saved.config.provider if saved else "ollama")
        )
        self.url.setText(saved.config.base_url if saved else "http://127.0.0.1:11434")
        self.auth.setCurrentIndex(self.auth.findData(saved.config.auth if saved else "none"))
        self.test.setEnabled(saved is not None)

    @Slot()
    def _provider(self) -> None:
        local = self.provider.currentData() == "ollama"
        self.url.setText("http://127.0.0.1:11434" if local else "https://api.openai.com/v1")
        self.auth.setCurrentIndex(0 if local else 1)
        self.auth.setEnabled(not local)

    @Slot()
    def _save(self) -> None:
        try:
            config = ModelConfig(
                label=self.name.text(),
                provider=self.provider.currentData(),
                model=self.model.text(),
                base_url=self.url.text(),
                auth=self.auth.currentData(),
            )
        except ValidationError:
            self.feedback.setText(ERRORS["config"])
            return
        secret = self.secret.text()
        self.secret.clear()
        self.controller.save(config, secret, self.selection.currentData())

    @Slot()
    def _test(self) -> None:
        model_id = self.selection.currentData()
        if model_id is not None:
            self.controller.test(model_id)

    @Slot()
    def _prefs(self) -> None:
        self.controller.preferences(
            Preferences(
                default_model_id=self.default.currentData(),
                local_first=self.local_first.isChecked(),
                reminders=self.reminders.isChecked(),
                reminder_days=self.days.value(),
            )
        )

    @Slot(bool)
    def _busy(self, busy: bool) -> None:
        self.setEnabled(not busy)


class AnalysisPanel(QWidget):
    def __init__(self, controller: AIController, mail: MailController) -> None:
        super().__init__()
        self.controller = controller
        self.mail = mail
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                "先在“邮件”页同步并选择目录，再从这里选择缓存邮件。默认本地处理；"
                "使用云端时将展示本封邮件的发送预览，每次都需授权。"
            )
        )
        self.messages = QComboBox()
        self.models = QComboBox()
        self.analyze = QPushButton("分析所选邮件")
        layout.addWidget(self.messages)
        layout.addWidget(self.models)
        layout.addWidget(self.analyze)
        split = QSplitter()
        self.results = QListWidget()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.results)
        split.addWidget(self.detail)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        self.feedback = label("尚未分析邮件。分析不会修改服务器状态。")
        layout.addWidget(self.feedback)
        mail.changed.connect(self._mail)
        controller.changed.connect(self.apply_snapshot)
        controller.status.connect(self.feedback.setText)
        controller.busy.connect(lambda busy: self.analyze.setEnabled(not busy))
        controller.approval.connect(self._approval)
        self.analyze.clicked.connect(self._analyze)
        self.results.currentRowChanged.connect(self._detail)

    @Slot(object)
    def _mail(self, value: object) -> None:
        if not isinstance(value, MailboxSnapshot):
            return
        selected = self.messages.currentData()
        self.messages.clear()
        for message in value.messages:
            self.messages.addItem(message.parsed.subject or "（无主题）", message.id)
        self.messages.setCurrentIndex(max(0, self.messages.findData(selected)))

    @Slot(object)
    def apply_snapshot(self, value: object) -> None:
        if not isinstance(value, AISnapshot):
            return
        selected = self.models.currentData()
        self.models.clear()
        self.models.addItem("按设置路由（默认本地优先）", None)
        for model in value.models:
            self.models.addItem(
                f"{model.config.label} · {'本机' if model.config.local else '云端，需授权'}",
                model.id,
            )
        self.models.setCurrentIndex(max(0, self.models.findData(selected)))
        self.results.clear()
        self.detail.clear()
        for row in value.analyses:
            result = Analysis.model_validate_json(str(row["result_json"]))
            self.results.addItem(f"{CATEGORY_LABELS[result.category]} · {row['subject']}")
        if value.analyses:
            self.results.setCurrentRow(0)

    @Slot(int)
    def _detail(self, index: int) -> None:
        if index < 0 or index >= len(self.controller.state.analyses):
            return
        row = self.controller.state.analyses[index]
        result = Analysis.model_validate_json(str(row["result_json"]))
        lines = [
            f"来源邮件 #{row['message_id']} · 分析规则 {row['skill_version']}",
            f"分类：{CATEGORY_LABELS[result.category]} · "
            f"优先级：{PRIORITY_LABELS[result.priority]}",
            f"保密等级：{CONFIDENTIALITY_LABELS[result.confidentiality]} · "
            f"模型置信度：{result.confidence:.0%}",
            result.summary,
            "原文证据：",
            "\n".join(result.evidence),
            "任务建议（请在待办页确认）：",
        ]
        lines += [
            f"{t.title} · {KIND_LABELS[t.deadline_kind]} · "
            f"{t.deadline or '日期待确认'}\n{t.evidence}"
            for t in result.tasks
        ]
        self.detail.setPlainText("\n\n".join(lines))

    @Slot()
    def _analyze(self) -> None:
        message_id = self.messages.currentData()
        if message_id is not None:
            self.controller.analyze(message_id, self.models.currentData())

    @Slot(object)
    def _approval(self, value: object) -> None:
        if not isinstance(value, CloudPreview):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("本次云端处理授权")
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            label(
                f"将发送邮件 #{value.message_id} 至 {value.model.config.base_url}\n"
                f"模型：{value.model.config.model}\n下方列出全部邮件字段。审稿、未发表材料和未知内容均按敏感处理。"
                "点击“授权发送并分析”仅授权这一封邮件、这个模型和本次请求。"
            )
        )
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(json.dumps(json.loads(value.source), ensure_ascii=False, indent=2))
        layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        approve = buttons.addButton("授权发送并分析", QDialogButtonBox.ButtonRole.AcceptRole)
        approve.setAutoDefault(False)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setDefault(True)
        buttons.rejected.connect(dialog.reject)
        approve.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.approve(value)


class TaskPanel(QWidget):
    def __init__(self, controller: AIController) -> None:
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(160)
        layout.addWidget(self.evidence)
        self.deadline = QLineEdit()
        self.deadline.setPlaceholderText("人工确认日期：YYYY-MM-DD；留空表示未知")
        self.deadline.setAccessibleName("人工确认截止日期")
        layout.addWidget(self.deadline)
        row = QHBoxLayout()
        self.confirm = QPushButton("确认任务与日期")
        self.done = QPushButton("完成")
        self.dismiss = QPushButton("忽略")
        for button in (self.confirm, self.done, self.dismiss):
            row.addWidget(button)
        layout.addLayout(row)
        self.feedback = label("模型提取的任务先列为待确认；提醒仅针对已确认任务。")
        layout.addWidget(self.feedback)
        self.list.currentRowChanged.connect(self._detail)
        self.confirm.clicked.connect(lambda: self._update("confirmed", True))
        self.done.clicked.connect(lambda: self._update("done"))
        self.dismiss.clicked.connect(lambda: self._update("dismissed"))
        controller.changed.connect(self.apply_snapshot)
        controller.status.connect(self.feedback.setText)
        controller.busy.connect(lambda busy: self.setEnabled(not busy))

    @Slot(object)
    def apply_snapshot(self, value: object) -> None:
        if not isinstance(value, AISnapshot):
            return
        self.list.clear()
        self.evidence.clear()
        self.deadline.clear()
        for task in value.tasks:
            self.list.addItem(
                f"{STATUS_LABELS[task.status]} · {task.title}\n"
                f"{KIND_LABELS.get(task.deadline_kind or 'other', '其他')} · "
                f"{task.deadline or '日期待确认'}"
            )
        if value.tasks:
            self.list.setCurrentRow(0)

    @Slot(int)
    def _detail(self, index: int) -> None:
        if index < 0 or index >= len(self.controller.state.tasks):
            return
        task = self.controller.state.tasks[index]
        self.evidence.setPlainText(
            f"任务 #{task.id} · 来源邮件 #{task.message_id or '手工'}\n{task.evidence or ''}"
        )
        self.deadline.setText(str(task.deadline) if task.deadline else "")

    def _update(self, status: str, edit: bool = False) -> None:
        index = self.list.currentRow()
        if index < 0 or index >= len(self.controller.state.tasks):
            return
        try:
            deadline = date.fromisoformat(self.deadline.text()) if self.deadline.text() else None
        except ValueError:
            self.feedback.setText("请输入 YYYY-MM-DD 格式的有效日期，或留空。")
            return
        self.controller.task(self.controller.state.tasks[index].id, status, deadline, edit)
