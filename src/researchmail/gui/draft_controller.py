from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal, Slot

from researchmail.drafts.models import ERRORS, Draft, DraftContent, DraftError, SendPreview
from researchmail.gui.worker import Worker
from researchmail.llm.models import ERRORS as AI_ERRORS
from researchmail.llm.models import AIError
from researchmail.services.draft_service import DraftService
from researchmail.storage.database import StorageError


@dataclass(frozen=True)
class DraftSnapshot:
    drafts: list[Draft]
    selected_id: int | None
    feedback: str = ""


@dataclass(frozen=True)
class PreviewAction:
    preview: SendPreview
    action: str


class DraftController(QObject):
    changed = Signal(object)
    status = Signal(str)
    busy = Signal(bool)
    preview_ready = Signal(object)

    def __init__(self, service: DraftService, pool: QThreadPool, parent: QObject) -> None:
        super().__init__(parent)
        self.service = service
        self.pool = pool
        self.jobs: set[Worker] = set()
        self.state = DraftSnapshot([], None)

    def run(
        self,
        operation: Callable[[], object],
        text: str,
        select: int | None = None,
        refresh_on_error: bool = False,
    ) -> None:
        if self.jobs:
            return
        selected = select if select is not None else self.state.selected_id

        def execute() -> object:
            try:
                result = operation()
                if isinstance(result, (PreviewAction, DraftSnapshot)):
                    return result
                draft_id = result if type(result) is int else selected
                return DraftSnapshot(self.service.repository.list(), draft_id)
            except DraftError as error:
                if refresh_on_error:
                    return DraftSnapshot(
                        self.service.repository.list(), selected, ERRORS[error.code]
                    )
                return ERRORS[error.code]
            except AIError as error:
                return AI_ERRORS[error.code]
            except (StorageError, OSError, ValueError):
                return ERRORS["storage"]

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
            self.status.emit(result)
        elif isinstance(result, PreviewAction):
            QTimer.singleShot(0, lambda: self.preview_ready.emit(result))
        elif isinstance(result, DraftSnapshot):
            self.state = result
            self.changed.emit(result)
            self.status.emit(result.feedback or "草稿状态已更新；发送仅在本次明确确认后执行。")

    @Slot()
    def _finished(self) -> None:
        self.jobs.clear()
        self.busy.emit(False)

    def refresh(self, recover: bool = False) -> None:
        def load() -> None:
            if recover:
                self.service.recover_interrupted()

        self.run(load, "正在读取本地草稿…")

    def create(self, content: DraftContent) -> None:
        self.run(lambda: self.service.repository.create(content), "正在创建本地草稿…")

    def reply(self, message_id: int, intent: str, model_id: int | None, use_model: bool) -> None:
        self.run(
            lambda: self.service.create_reply(message_id, intent, model_id, use_model),
            "正在生成本地回复草稿…",
        )

    def save(self, draft: Draft, content: DraftContent) -> None:
        self.run(
            lambda: self.service.repository.save(draft.id, content, draft.revision),
            "正在保存草稿…",
            draft.id,
        )

    def preview(self, draft_id: int, action: str) -> None:
        self.run(
            lambda: PreviewAction(self.service.repository.preview(draft_id), action),
            "正在核对当前草稿与发件配置…",
            draft_id,
        )

    def confirm(self, value: PreviewAction) -> None:
        preview = value.preview

        def apply() -> object:
            if value.action == "send":
                token = self.service.authorize_send(preview)
                return self.service.send_approved(preview.draft.id, token)
            self.service.repository.transition(preview.draft.id, preview.digest, value.action)
            return None

        self.run(
            apply,
            "正在发送，请等待服务器结果…" if value.action == "send" else "正在保存审核状态…",
            preview.draft.id,
            refresh_on_error=value.action == "send",
        )

    def reopen(self, draft_id: int) -> None:
        self.run(
            lambda: self.service.repository.reset_failed(draft_id),
            "正在重置为待审核草稿…",
            draft_id,
        )

    def test_smtp(self, account_id: int) -> None:
        def test() -> object:
            self.service.test_smtp(account_id)
            return DraftSnapshot(
                self.service.repository.list(),
                self.state.selected_id,
                "SMTP SSL 认证成功；未提交邮件。",
            )

        self.run(test, "正在测试 SMTP SSL 认证，不提交邮件…")
