from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from researchmail import __version__
from researchmail.eventlog import Event, EventLog
from researchmail.gui.ai_controller import AIController, AISnapshot
from researchmail.gui.ai_widgets import AnalysisPanel, ModelEditor, TaskPanel
from researchmail.gui.draft_controller import DraftController
from researchmail.gui.draft_widgets import DraftPanel
from researchmail.gui.mail_controller import MailController
from researchmail.gui.mail_widgets import AccountEditor, MailBrowser
from researchmail.gui.onboarding import OnboardingWizard
from researchmail.gui.worker import Worker
from researchmail.services.ai_service import AIService
from researchmail.services.draft_service import DraftService
from researchmail.services.mail_service import MailService
from researchmail.services.workspace import WorkspaceService, WorkspaceState

NAVIGATION = ("今日", "邮件", "审稿与投稿", "待办", "草稿", "设置")


def text_label(text: str, size: int = 13, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    font = QFont(label.font())
    font.setPointSize(size)
    font.setBold(bold)
    label.setFont(font)
    return label


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: WorkspaceService,
        event_log: EventLog | None = None,
        mail_service: MailService | None = None,
        ai_service: AIService | None = None,
        draft_service: DraftService | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.event_log = event_log
        self.pool = QThreadPool(self)
        self.mail_controller = MailController(
            mail_service if mail_service is not None else MailService(service.database),
            self.pool,
            self,
        )
        self.ai_controller = AIController(
            ai_service if ai_service is not None else AIService(service.database), self.pool, self
        )
        self.draft_controller = DraftController(
            draft_service
            if draft_service is not None
            else DraftService(service.database, ai=self.ai_controller.service),
            self.pool,
            self,
        )
        self.jobs: set[Worker] = set()
        self.wizard: OnboardingWizard | None = None
        self.ready = False
        self.setWindowTitle("ResearchMail Agent")
        self.resize(1100, 740)
        self.setMinimumSize(820, 600)

        splitter = QSplitter()
        self.setCentralWidget(splitter)
        sidebar = QWidget()
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(270)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(20, 28, 16, 20)
        side_layout.setSpacing(12)
        side_layout.addWidget(text_label("ResearchMail", 18, True))
        side_layout.addWidget(text_label("科研邮件工作区", 12))
        self.navigation = QListWidget()
        self.navigation.setAccessibleName("主导航")
        self.navigation.addItems(NAVIGATION)
        self.navigation.setSpacing(7)
        side_layout.addWidget(self.navigation)
        side_layout.addWidget(text_label(f"M3 开发版 · {__version__}", 11))
        side_layout.addWidget(text_label("收信只读 · 发信需审批", 11))
        splitter.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.setAccessibleName("工作区内容")
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self._build_pages()
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._draft_navigation)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage("正在检查本地工作区…")
        self.mail_controller.status.connect(self.statusBar().showMessage)
        self.ai_controller.status.connect(self.statusBar().showMessage)
        self.draft_controller.status.connect(self.statusBar().showMessage)
        self.ai_controller.reminder.connect(self._reminder)
        self.ai_controller.changed.connect(self._ai_changed)
        self._build_menu()
        QTimer.singleShot(0, self.initialize)

    def _page(self, title: str, subtitle: str) -> QVBoxLayout:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(18)
        layout.addWidget(text_label(title, 26, True))
        layout.addWidget(text_label(subtitle))
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def _build_pages(self) -> None:
        today = self._page("今日", QDate.currentDate().toString("yyyy年M月d日"))
        today.addWidget(text_label("已确认任务与近期截止", 19, True))
        self.reminder_label = text_label("提醒可在设置中开启；仅在应用运行期间显示。")
        today.addWidget(self.reminder_label)
        self.daily_digest = QPlainTextEdit()
        self.daily_digest.setReadOnly(True)
        self.daily_digest.setPlaceholderText("确认任务后，在此查看本地日报。")
        today.addWidget(self.daily_digest, 1)
        refresh = QPushButton("刷新本地日报")
        refresh.clicked.connect(self.ai_controller.refresh)
        today.addWidget(refresh, alignment=Qt.AlignmentFlag.AlignLeft)
        settings = QPushButton("查看工作区设置")
        settings.clicked.connect(lambda: self.navigation.setCurrentRow(5))
        today.addWidget(settings, alignment=Qt.AlignmentFlag.AlignLeft)
        mail_layout = self._page("邮件", "服务器邮件只读 · 正文按纯文本显示")
        self.mail_browser = MailBrowser(self.mail_controller)
        mail_layout.addWidget(self.mail_browser, 1)
        review_layout = self._page("审稿与投稿", "分析缓存邮件 · 原文证据与任务建议")
        self.analysis_panel = AnalysisPanel(self.ai_controller, self.mail_controller)
        review_layout.addWidget(self.analysis_panel, 1)
        task_layout = self._page("待办", "区分邀请回复、审稿报告、退修和校样期限")
        self.task_panel = TaskPanel(self.ai_controller)
        task_layout.addWidget(self.task_panel, 1)
        drafts = self._page("草稿", "草稿编辑、人工审核与受控发送")
        drafts.setSpacing(10)
        drafts.setContentsMargins(28, 24, 28, 24)
        self.draft_panel = DraftPanel(
            self.draft_controller, self.mail_controller, self.ai_controller
        )
        drafts.addWidget(self.draft_panel, 1)
        layout = self._page("设置", "本机数据与诊断")
        self.account_editor = AccountEditor(self.mail_controller)
        layout.addWidget(self.account_editor)
        smtp_test = QPushButton("测试已保存账户的 SMTP 认证（不发送）")
        smtp_test.clicked.connect(self._smtp_test)
        layout.addWidget(smtp_test)
        self.model_editor = ModelEditor(self.ai_controller)
        layout.addWidget(self.model_editor)
        layout.addWidget(text_label("隐私规则", 17, True))
        layout.addWidget(text_label("默认本地处理；保密级别未知时按敏感处理。云端处理需明确授权。"))
        layout.addWidget(text_label("本地数据", 17, True))
        self.storage_status = text_label("正在检查数据库…")
        layout.addWidget(self.storage_status)
        location = text_label(str(self.service.paths.data), 12)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)
        self.backup_button = QPushButton("创建本地数据库备份")
        self.backup_button.setEnabled(False)
        self.backup_button.clicked.connect(self.backup)
        layout.addWidget(self.backup_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(
            text_label("备份保存在本机数据目录的 backups 文件夹中。备份未加密，请妥善保管。", 12)
        )
        self.backup_status = text_label("")
        self.backup_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.backup_status)
        layout.addWidget(text_label("功能进度", 17, True))
        layout.addWidget(
            text_label(
                "已支持：只读邮箱、Keychain、本地与云端模型、分类摘要、任务确认与应用内提醒\n"
                "已支持：本地草稿生成、编辑、审核、审批与受控 SMTP 发送\n"
                "M4：Developer ID 签名、公证与正式分发"
            )
        )
        row = QHBoxLayout()
        wizard_button = QPushButton("重新查看首次引导")
        wizard_button.clicked.connect(self.show_onboarding)
        row.addWidget(wizard_button)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(text_label(f"ResearchMail Agent {__version__} · M3 开发版", 12))
        layout.addWidget(
            text_label("使用系统外观。无需 Ollama 即可启动；模型需在本机配置后启用。", 12)
        )
        layout.addStretch()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("工作区")
        settings = QAction("设置…", self)
        settings.setShortcut(QKeySequence("Ctrl+,"))
        settings.triggered.connect(lambda: self.navigation.setCurrentRow(5))
        menu.addAction(settings)
        quit_action = QAction("退出 ResearchMail Agent", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def _event(self, event: Event) -> None:
        if self.event_log is not None:
            self.event_log.write(event)

    def _run(
        self,
        operation: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[], None],
    ) -> None:
        worker = Worker(operation)
        self.jobs.add(worker)
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(failure)
        worker.signals.finished.connect(lambda: self.jobs.discard(worker))
        self.pool.start(worker)

    @Slot()
    def initialize(self) -> None:
        self._run(self.service.initialize, self._initialized, self._storage_failed)

    @Slot(object)
    def _initialized(self, state: object) -> None:
        if not isinstance(state, WorkspaceState):
            self._storage_failed()
            return
        self.ready = True
        self.storage_status.setText(f"数据库正常 · 迁移版本 {state.schema_version} · WAL 已启用")
        self.statusBar().showMessage("本地工作区已就绪 · 尚未连接邮箱")
        self.backup_button.setEnabled(True)
        self.mail_controller.refresh()
        self.ai_controller.refresh()
        self.draft_controller.refresh(recover=True)
        self._event(Event.STARTUP_OK)
        if not state.onboarding_completed:
            self.show_onboarding()

    @Slot()
    def _storage_failed(self) -> None:
        self.ready = False
        self.backup_button.setEnabled(False)
        message = "无法打开本地数据。请检查磁盘空间与文件权限；原文件已保留，请勿删除。"
        self.storage_status.setText(message)
        self.statusBar().showMessage(message)
        self._event(Event.STORAGE_FAILED)

    @Slot()
    def show_onboarding(self) -> None:
        if not self.ready:
            return
        if self.wizard is not None:
            self.wizard.raise_()
            return
        wizard = OnboardingWizard()
        wizard.setParent(self, Qt.WindowType.Dialog)
        self.wizard = wizard
        wizard.accepted.connect(self._onboarding_accepted)
        wizard.finished.connect(self._wizard_finished)
        wizard.open()

    @Slot(int)
    def _wizard_finished(self, result: int) -> None:
        if self.wizard is not None:
            self.wizard.deleteLater()
            self.wizard = None

    @Slot()
    def _onboarding_accepted(self) -> None:
        self._run(self.service.complete_onboarding, self._onboarding_saved, self._storage_failed)

    @Slot(object)
    def _onboarding_saved(self, result: object) -> None:
        self.statusBar().showMessage("引导已完成 · 本地工作区已就绪")
        self._event(Event.ONBOARDING_OK)

    @Slot()
    def backup(self) -> None:
        self.backup_button.setEnabled(False)
        self.backup_status.setText("正在创建一致性备份…")
        self._run(self.service.backup, self._backup_saved, self._backup_failed)

    @Slot(object)
    def _backup_saved(self, result: object) -> None:
        if not isinstance(result, Path):
            self._backup_failed()
            return
        self.backup_status.setText(f"备份已保存：\n{result}")
        self.backup_button.setEnabled(True)
        self._event(Event.BACKUP_OK)

    @Slot()
    def _backup_failed(self) -> None:
        self.backup_status.setText("备份未完成。请检查磁盘空间与文件权限后重试，原数据未更改。")
        self.backup_button.setEnabled(True)
        self._event(Event.BACKUP_FAILED)

    @Slot()
    def _smtp_test(self) -> None:
        account_id = self.account_editor.account_id
        if account_id is not None:
            self.draft_controller.test_smtp(account_id)
        else:
            self.statusBar().showMessage("请先保存并选择发件账户。")

    @Slot(int)
    def _draft_navigation(self, row: int) -> None:
        if row == 4 and self.ready and not self.draft_panel.dirty:
            self.draft_controller.refresh()

    @Slot(object)
    def _ai_changed(self, value: object) -> None:
        if isinstance(value, AISnapshot):
            self.daily_digest.setPlainText(value.digest)

    @Slot(str)
    def _reminder(self, text: str) -> None:
        self.reminder_label.setText("截止提醒：" + text)
        self.statusBar().showMessage("有已确认任务临近截止，请查看今日页。")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.draft_panel.dirty:
            self.statusBar().showMessage("草稿有未保存修改。请先保存，或点击撤销未保存修改后退出。")
            event.ignore()
            return
        if (
            self.jobs
            or self.mail_controller.jobs
            or self.ai_controller.jobs
            or self.draft_controller.jobs
        ):
            self.mail_controller.cancel.set()
            self.statusBar().showMessage("正在停止操作，请等待本次网络请求结束后再退出。")
            event.ignore()
            return
        if self.wizard is not None:
            self.wizard.reject()
        event.accept()


def startup_error() -> None:
    QMessageBox.critical(
        None,
        "无法启动 ResearchMail Agent",
        "无法创建本地工作区。请检查用户目录权限与磁盘空间后重新启动。",
    )
