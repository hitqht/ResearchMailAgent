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
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from researchmail import __version__
from researchmail.eventlog import Event, EventLog
from researchmail.gui.onboarding import OnboardingWizard
from researchmail.gui.worker import Worker
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
    def __init__(self, service: WorkspaceService, event_log: EventLog | None = None) -> None:
        super().__init__()
        self.service = service
        self.event_log = event_log
        self.pool = QThreadPool(self)
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
        side_layout.addWidget(text_label(f"M0 工程预览 · {__version__}", 11))
        side_layout.addWidget(text_label("本地工作区 · 尚未连接邮箱", 11))
        splitter.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.setAccessibleName("工作区内容")
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self._build_pages()
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage("正在检查本地工作区…")
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
        today.addWidget(text_label("先建立一个安心的科研工作区", 19, True))
        today.addWidget(
            text_label(
                "这里将汇集审稿、投稿与合作邮件中的待办。当前版本已建立本地数据库和隐私边界。"
            )
        )
        today.addStretch()
        today.addWidget(text_label("开始之前", 16, True))
        today.addWidget(
            text_label("01  了解本地存储与隐私规则\n02  查看设置与诊断\n03  等待 M1 邮箱接入")
        )
        settings = QPushButton("查看工作区设置")
        settings.clicked.connect(lambda: self.navigation.setCurrentRow(5))
        today.addWidget(settings, alignment=Qt.AlignmentFlag.AlignLeft)
        for title, subtitle, body in (
            ("邮件", "邮箱接入将在 M1 提供", "尚未连接邮箱\n\n连接后将在这里显示只读同步的邮件。"),
            (
                "审稿与投稿",
                "科研邮件分析将在 M2 提供",
                "尚无科研事项\n\n邀请回复、审稿报告、退修和校样期限将分别呈现。",
            ),
            (
                "待办",
                "任务提取与提醒将在 M2 提供",
                "尚无待办\n\n邮件中提取的任务需要你确认；不确定的日期将保留为空。",
            ),
            ("草稿", "草稿与审批将在 M3 提供", "尚无草稿\n\n当前版本没有邮件发送路径。"),
        ):
            layout = self._page(title, subtitle)
            layout.addStretch()
            layout.addWidget(text_label(body, 16), alignment=Qt.AlignmentFlag.AlignCenter)
            layout.addStretch()
        layout = self._page("设置", "本机数据与诊断")
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
                "M1：邮箱账户、Keychain、连接测试与同步周期\n"
                "M2：本地与云端模型、认证、提醒\nM3：草稿编辑、审批与受控发送"
            )
        )
        row = QHBoxLayout()
        wizard_button = QPushButton("重新查看首次引导")
        wizard_button.clicked.connect(self.show_onboarding)
        row.addWidget(wizard_button)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(text_label(f"ResearchMail Agent {__version__} · M0 工程预览", 12))
        layout.addWidget(
            text_label("使用系统外观。无需 Ollama 即可启动；当前没有启用任何模型。", 12)
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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.jobs:
            self.statusBar().showMessage("正在完成本地数据操作，请稍后再退出。")
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
