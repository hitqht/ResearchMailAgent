from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal, Slot

from researchmail.gui.worker import Worker
from researchmail.llm.models import (
    ERRORS,
    AIError,
    ModelConfig,
    Preferences,
    SavedModel,
    TaskRecord,
)
from researchmail.mail.models import MailError
from researchmail.services.ai_service import AIService
from researchmail.storage.database import StorageError


@dataclass(frozen=True)
class AISnapshot:
    models: list[SavedModel]
    preferences: Preferences
    tasks: list[TaskRecord]
    analyses: list[dict[str, object]]
    digest: str


@dataclass(frozen=True)
class CloudPreview:
    message_id: int
    model: SavedModel
    source: str


class AIController(QObject):
    changed = Signal(object)
    status = Signal(str)
    busy = Signal(bool)
    approval = Signal(object)
    reminder = Signal(str)

    def __init__(self, service: AIService, pool: QThreadPool, parent: QObject) -> None:
        super().__init__(parent)
        self.service = service
        self.pool = pool
        self.jobs: set[Worker] = set()
        self.state = AISnapshot([], Preferences(), [], [], "尚无已确认任务。")
        self._reminded: set[tuple[str, int, str]] = set()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_reminders)
        self.timer.start(60_000)

    def snapshot(self) -> AISnapshot:
        repo = self.service.repository
        return AISnapshot(
            repo.models(), repo.preferences(), repo.tasks(), repo.analyses(), repo.digest()
        )

    def run(self, action: Callable[[], object], text: str) -> None:
        if self.jobs:
            return

        def execute() -> object:
            try:
                result = action()
                return result if isinstance(result, CloudPreview) else self.snapshot()
            except AIError as error:
                return error.code
            except MailError:
                return "keychain"
            except (StorageError, ValueError, KeyError):
                return "storage"

        worker = Worker(execute)
        self.jobs.add(worker)
        worker.signals.succeeded.connect(self._result)
        worker.signals.failed.connect(lambda: self.status.emit(ERRORS["storage"]))
        worker.signals.finished.connect(self._finished)
        self.status.emit(text)
        self.busy.emit(True)
        self.pool.start(worker)

    @Slot(object)
    def _result(self, result: object) -> None:
        if isinstance(result, str):
            self.status.emit(ERRORS.get(result, ERRORS["storage"]))
        elif isinstance(result, CloudPreview):
            # Finish signal follows this one. Defer dialog so the next action can start a worker.
            QTimer.singleShot(0, lambda: self.approval.emit(result))
        elif isinstance(result, AISnapshot):
            self.state = result
            self.changed.emit(result)
            self.status.emit("本地工作区已更新。任务建议需要确认。")
            self.check_reminders()

    @Slot()
    def _finished(self) -> None:
        self.jobs.clear()
        self.busy.emit(False)

    @Slot()
    def refresh(self) -> None:
        self.run(lambda: None, "正在读取本地模型与任务…")

    def save(self, config: ModelConfig, secret: str, model_id: int | None) -> None:
        self.run(
            lambda: self.service.save_model(config, secret, model_id), "正在保存模型配置与钥匙串…"
        )

    def preferences(self, prefs: Preferences) -> None:
        self.run(lambda: self.service.repository.save_preferences(prefs), "正在保存偏好…")

    def test(self, model_id: int) -> None:
        self.run(lambda: self.service.test_connection(model_id), "正在测试模型，发送固定合成提示…")

    def analyze(self, message_id: int, model_id: int | None = None) -> None:
        def prepare() -> object:
            model = self.service.resolve(model_id)
            if model.config.local:
                return self.service.analyze(message_id, model.id)
            return CloudPreview(message_id, model, self.service.repository.source(message_id))

        self.run(prepare, "正在检查隐私路由与分析邮件…")

    def approve(self, preview: CloudPreview) -> None:
        def analyze() -> object:
            repo = self.service.repository
            if (
                repo.source(preview.message_id) != preview.source
                or repo.model(preview.model.id).config != preview.model.config
            ):
                raise AIError("privacy")
            token = self.service.authorize_cloud(
                preview.message_id,
                preview.model.id,
                expected_source=preview.source,
                expected_config=preview.model.config,
            )
            return self.service.analyze(preview.message_id, preview.model.id, token)

        self.run(analyze, "正在按本次授权分析所选邮件…")

    def task(
        self, task_id: int, status: str, deadline: date | None = None, edit_deadline: bool = False
    ) -> None:
        self.run(
            lambda: self.service.repository.update_task(task_id, status, deadline, edit_deadline),
            "正在更新本地任务…",
        )

    def check_reminders(self) -> None:
        prefs = self.state.preferences
        if not prefs.reminders:
            return
        today = date.today()
        for task in self.state.tasks:
            if (
                task.status != "confirmed"
                or task.deadline is None
                or task.deadline > today + timedelta(days=prefs.reminder_days)
            ):
                continue
            key = (today.isoformat(), task.id, task.deadline.isoformat())
            if key not in self._reminded:
                self._reminded.add(key)
                self.reminder.emit(f"任务 #{task.id} · {task.title} · 截止 {task.deadline}")
