from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal()
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception:
            # Deliberately do not transport raw exceptions (may contain sensitive data).
            self.signals.failed.emit()
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()
