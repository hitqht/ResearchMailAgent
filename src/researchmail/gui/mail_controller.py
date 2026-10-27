from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal, Slot

from researchmail.gui.worker import Worker
from researchmail.mail.models import (
    ERROR_TEXT,
    Account,
    AccountConfig,
    Failure,
    Folder,
    MessageView,
)
from researchmail.services.mail_service import MailService, Outcome, safely


@dataclass(frozen=True)
class MailboxSnapshot:
    accounts: list[Account]
    account_id: int | None
    folders: list[Folder]
    folder: str
    messages: list[MessageView]
    search: str = ""
    offset: int = 0
    status: str = "本地缓存 · 服务器邮件始终只读"


class MailController(QObject):
    changed = Signal(object)
    status = Signal(str)
    busy_changed = Signal(bool)
    progress = Signal(int, int)

    def __init__(self, service: MailService, pool: QThreadPool, parent: QObject) -> None:
        super().__init__(parent)
        self.service = service
        self.pool = pool
        self.jobs: set[Worker] = set()
        self.state = MailboxSnapshot([], None, [], "INBOX", [])
        self.cancel = Event()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync)
        self._schedule: tuple[int | None, int] = (None, 0)

    def snapshot(
        self,
        account_id: int | None = None,
        folder: str = "INBOX",
        search: str = "",
        offset: int = 0,
        status: str = "本地缓存 · 服务器邮件始终只读",
    ) -> MailboxSnapshot:
        repository = self.service.repository
        accounts = repository.accounts()
        if account_id not in {a.id for a in accounts}:
            account_id = accounts[0].id if accounts else None
        folders = repository.folders(account_id) if account_id is not None else []
        selectable = [f.wire_name for f in folders if f.selectable]
        if selectable and folder not in selectable:
            folder = "INBOX" if "INBOX" in selectable else selectable[0]
        messages = repository.messages(account_id, folder, search, offset) if account_id else []
        return MailboxSnapshot(
            accounts, account_id, folders, folder, messages, search, offset, status
        )

    def _run(self, operation: Callable[[Callable[[int, int], None]], MailboxSnapshot]) -> None:
        if self.jobs:
            return
        self.cancel.clear()
        worker = Worker(lambda: safely(lambda: operation(worker.signals.progress.emit)))
        self.jobs.add(worker)
        worker.signals.succeeded.connect(self._result)
        worker.signals.failed.connect(self._failed)
        worker.signals.progress.connect(self.progress)
        worker.signals.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self.pool.start(worker)

    @Slot(object)
    def _result(self, value: object) -> None:
        if not isinstance(value, Outcome):
            self._failed()
            return
        if value.error is not None:
            self.status.emit(ERROR_TEXT[value.error])
            return
        if not isinstance(value.value, MailboxSnapshot):
            self._failed()
            return
        self.state = value.value
        self.changed.emit(self.state)
        self.status.emit(self.state.status)
        selected = next((a for a in self.state.accounts if a.id == self.state.account_id), None)
        minutes = selected.config.sync_minutes if selected else 0
        schedule = (self.state.account_id, minutes)
        if schedule != self._schedule:
            self.timer.stop()
            if minutes:
                self.timer.start(minutes * 60_000)
            self._schedule = schedule

    @Slot()
    def _failed(self) -> None:
        self.status.emit(ERROR_TEXT[Failure.STORAGE])

    @Slot()
    def _finished(self) -> None:
        self.jobs.clear()
        self.busy_changed.emit(False)

    def refresh(
        self,
        account_id: int | None = None,
        folder: str = "INBOX",
        search: str = "",
        offset: int = 0,
    ) -> None:
        self._run(lambda progress: self.snapshot(account_id, folder, search, offset))

    def save_account(self, config: AccountConfig, secret: str, account_id: int | None) -> None:
        def save(progress: Callable[[int, int], None]) -> MailboxSnapshot:
            saved = self.service.save_account(config, secret, account_id)
            return self.snapshot(saved, status="账户已保存至本机，授权码存于 macOS 钥匙串。")

        self._run(save)

    def test_connection(self, account_id: int) -> None:
        def test(progress: Callable[[int, int], None]) -> MailboxSnapshot:
            folders = self.service.test_connection(account_id)
            return self.snapshot(
                account_id, self.state.folder, status=f"只读连接成功 · 已读取 {len(folders)} 个目录"
            )

        self.status.emit("正在测试 SSL 连接与读取目录…")
        self._run(test)

    @Slot()
    def sync(self) -> None:
        state = self.state
        if state.account_id is None or self.jobs:
            return
        account_id = state.account_id

        def sync(progress: Callable[[int, int], None]) -> MailboxSnapshot:
            result = self.service.sync(account_id, state.folder, self.cancel, progress)
            text = f"{'已停止' if result.cancelled else '同步完成'} · 新增 {result.imported} 封"
            if result.remaining:
                text += f" · 还有 {result.remaining} 封，可继续同步"
            if result.uidvalidity_changed:
                text += " · 服务器目录标识已变更，旧缓存已保留"
            return self.snapshot(state.account_id, state.folder, state.search, 0, text)

        self.status.emit("正在只读同步，每批最多 100 封…")
        self._run(sync)
