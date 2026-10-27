from pydantic import ValidationError
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from researchmail.gui.mail_controller import MailboxSnapshot, MailController
from researchmail.mail.models import ERROR_TEXT, Account, AccountConfig, Failure, Folder


def label(text: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class AccountEditor(QWidget):
    def __init__(self, controller: MailController) -> None:
        super().__init__()
        self.controller = controller
        self.accounts: list[Account] = []
        self.account_id: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(label("邮箱账户 · SSL 只读访问"))
        self.selector = QComboBox()
        self.selector.setAccessibleName("编辑邮箱账户")
        layout.addWidget(self.selector)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.email = QLineEdit()
        self.name = QLineEdit()
        self.imap_host = QLineEdit("imap.163.com")
        self.imap_port = QSpinBox()
        self.imap_port.setRange(1, 65535)
        self.imap_port.setValue(993)
        self.smtp_host = QLineEdit("smtp.163.com")
        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        self.smtp_port.setValue(465)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("客户端授权码；编辑时留空表示保留原值")
        self.interval = QSpinBox()
        self.interval.setRange(0, 1440)
        self.interval.setSpecialValueText("仅手动同步")
        self.interval.setSuffix(" 分钟（最少5分钟）")
        for title, widget in (
            ("邮箱地址", self.email),
            ("显示名称", self.name),
            ("IMAP 服务器", self.imap_host),
            ("IMAP SSL 端口", self.imap_port),
            ("SMTP 服务器（预留）", self.smtp_host),
            ("SMTP SSL 端口（预留）", self.smtp_port),
            ("客户端授权码", self.secret),
            ("同步当前目录", self.interval),
        ):
            widget.setAccessibleName(title)
            form.addRow(title, widget)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.save = QPushButton("保存到本机")
        self.test = QPushButton("测试已保存的连接")
        row.addWidget(self.save)
        row.addWidget(self.test)
        layout.addLayout(row)
        layout.addWidget(label("请先在163网页邮箱开启 IMAP，再填写客户端授权码。默认仅手动同步。"))
        self.feedback = label()
        layout.addWidget(self.feedback)
        self.selector.currentIndexChanged.connect(self._selected)
        self.save.clicked.connect(self._save)
        self.test.clicked.connect(self._test)
        controller.changed.connect(self.apply_snapshot)
        controller.status.connect(self.feedback.setText)
        controller.busy_changed.connect(lambda busy: self.setEnabled(not busy))
        self.selector.addItem("新建邮箱账户", None)

    @Slot(object)
    def apply_snapshot(self, value: object) -> None:
        if not isinstance(value, MailboxSnapshot) or value.accounts == self.accounts:
            return
        self.accounts = value.accounts
        self.selector.blockSignals(True)
        self.selector.clear()
        for account in self.accounts:
            self.selector.addItem(account.config.display_name or account.config.email, account.id)
        self.selector.addItem("新建邮箱账户", None)
        index = self.selector.findData(value.account_id)
        self.selector.setCurrentIndex(max(index, 0))
        self.selector.blockSignals(False)
        self._selected()

    @Slot()
    def _selected(self) -> None:
        self.account_id = self.selector.currentData()
        account = next((a for a in self.accounts if a.id == self.account_id), None)
        config = account.config if account else AccountConfig(email="user@example.invalid")
        self.email.setText(config.email if account else "")
        self.name.setText(config.display_name)
        self.imap_host.setText(config.imap_host)
        self.imap_port.setValue(config.imap_port)
        self.smtp_host.setText(config.smtp_host)
        self.smtp_port.setValue(config.smtp_port)
        self.interval.setValue(config.sync_minutes)
        self.secret.clear()
        self.test.setEnabled(account is not None)

    @Slot()
    def _save(self) -> None:
        try:
            config = AccountConfig(
                email=self.email.text(),
                display_name=self.name.text(),
                imap_host=self.imap_host.text(),
                imap_port=self.imap_port.value(),
                smtp_host=self.smtp_host.text(),
                smtp_port=self.smtp_port.value(),
                sync_minutes=self.interval.value(),
            )
        except ValidationError:
            self.feedback.setText(ERROR_TEXT[Failure.CONFIG])
            return
        secret = self.secret.text()
        self.secret.clear()
        self.controller.save_account(config, secret, self.account_id)

    @Slot()
    def _test(self) -> None:
        if self.account_id is not None:
            self.controller.test_connection(self.account_id)


class MailBrowser(QWidget):
    def __init__(self, controller: MailController) -> None:
        super().__init__()
        self.controller = controller
        self.snapshot = controller.state
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.account = QComboBox()
        self.folder = QComboBox()
        self.account.setAccessibleName("浏览邮箱账户")
        self.folder.setAccessibleName("邮件目录")
        self.test = QPushButton("读取目录 / 测试连接")
        self.sync = QPushButton("只读同步")
        self.stop = QPushButton("停止同步")
        for widget in (self.account, self.folder, self.test, self.sync, self.stop):
            row.addWidget(widget)
        layout.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索本地缓存的主题或发件人，按回车")
        self.search.setAccessibleName("搜索本地邮件")
        layout.addWidget(self.search)
        splitter = QSplitter()
        self.messages = QListWidget()
        self.messages.setAccessibleName("邮件列表")
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName("邮件纯文本详情")
        self.detail.setPlaceholderText("选择一封邮件查看。邮件内容不会执行指令或打开外部链接。")
        splitter.addWidget(self.messages)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        page = QHBoxLayout()
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        page.addWidget(self.previous)
        page.addWidget(self.next)
        page.addStretch()
        layout.addLayout(page)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.feedback = label("请到设置中添加邮箱。连接和同步都由你发起，默认不自动同步。")
        layout.addWidget(self.feedback)
        self.account.currentIndexChanged.connect(self._selection)
        self.folder.currentIndexChanged.connect(self._selection)
        self.search.returnPressed.connect(self._selection)
        self.messages.currentRowChanged.connect(self._detail)
        self.sync.clicked.connect(controller.sync)
        self.stop.clicked.connect(controller.cancel.set)
        self.test.clicked.connect(self._test)
        self.previous.clicked.connect(lambda: self._page(-100))
        self.next.clicked.connect(lambda: self._page(100))
        controller.changed.connect(self.apply_snapshot)
        controller.status.connect(self.feedback.setText)
        controller.busy_changed.connect(self._busy)
        controller.progress.connect(self._progress)
        self.stop.setEnabled(False)
        self._busy(False)

    @Slot(object)
    def apply_snapshot(self, value: object) -> None:
        if not isinstance(value, MailboxSnapshot):
            return
        self.snapshot = value
        self.account.blockSignals(True)
        self.folder.blockSignals(True)
        self.account.clear()
        for account in value.accounts:
            self.account.addItem(account.config.display_name or account.config.email, account.id)
        self.account.setCurrentIndex(self.account.findData(value.account_id))
        self.folder.clear()
        for folder in value.folders or [Folder("INBOX", "收件箱")]:
            if folder.selectable:
                self.folder.addItem(folder.display_name, folder.wire_name)
        self.folder.setCurrentIndex(self.folder.findData(value.folder))
        self.account.blockSignals(False)
        self.folder.blockSignals(False)
        self.search.setText(value.search)
        self.messages.clear()
        self.detail.clear()
        for message in value.messages:
            parsed = message.parsed
            self.messages.addItem(
                f"{parsed.subject or '（无主题）'}\n{parsed.sender or '（发件人未知）'}"
            )
        if not value.messages:
            self.detail.setPlainText("当前目录没有缓存邮件。可点击“只读同步”读取服务器邮件。")
        self._busy(bool(self.controller.jobs))

    @Slot()
    def _selection(self) -> None:
        self.controller.refresh(
            self.account.currentData(), self.folder.currentData() or "INBOX", self.search.text()
        )

    def _page(self, amount: int) -> None:
        state = self.snapshot
        self.controller.refresh(
            state.account_id, state.folder, state.search, max(0, state.offset + amount)
        )

    @Slot(int)
    def _detail(self, index: int) -> None:
        if index < 0 or index >= len(self.snapshot.messages):
            return
        message = self.snapshot.messages[index]
        parsed = message.parsed
        attachments = "\n".join(
            f"• {a.name} · {a.content_type} · {a.size} 字节" for a in parsed.attachments
        )
        parse_status = {
            "ok": "正常",
            "malformed": "格式异常，已尽力解析",
            "oversized": "邮件过大，未下载正文",
        }[parsed.parse_status]
        self.detail.setPlainText(
            f"主题：{parsed.subject}\n发件人：{parsed.sender}\n"
            f"收件人：{', '.join(parsed.recipients)}\n"
            f"日期（UTC）：{parsed.received_at or '未知'}\n大小：{message.size_bytes} 字节\n"
            f"正文状态：{parse_status}\n\n"
            f"{parsed.body}\n\n"
            f"附件（仅元数据）：\n{attachments or '无'}"
        )

    @Slot()
    def _test(self) -> None:
        if self.snapshot.account_id is not None:
            self.controller.test_connection(self.snapshot.account_id)

    @Slot(bool)
    def _busy(self, busy: bool) -> None:
        for widget in (self.account, self.folder, self.search):
            widget.setEnabled(not busy)
        for button in (self.test, self.sync):
            button.setEnabled(not busy and self.snapshot.account_id is not None)
        self.stop.setEnabled(busy)
        self.previous.setEnabled(not busy and self.snapshot.offset > 0)
        self.next.setEnabled(not busy and len(self.snapshot.messages) == 100)
        self.progress.setVisible(busy)

    @Slot(int, int)
    def _progress(self, completed: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(completed)
        self.feedback.setText(f"正在只读同步：{completed}/{total}")
