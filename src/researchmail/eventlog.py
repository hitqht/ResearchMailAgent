"""Allowlisted event logging. Never accept mail, credentials, or exception messages."""

import logging
from enum import StrEnum
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Event(StrEnum):
    STARTUP_OK = "startup_ok"
    STORAGE_FAILED = "storage_failed"
    BACKUP_OK = "backup_ok"
    BACKUP_FAILED = "backup_failed"
    ONBOARDING_OK = "onboarding_ok"


class EventLog:
    def __init__(self, directory: Path) -> None:
        path = directory / "events.log"
        if path.is_symlink():
            raise OSError("Log file must not be a symbolic link")
        self.handler = RotatingFileHandler(path, maxBytes=256_000, backupCount=3, encoding="utf-8")
        path.chmod(0o600)
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

    def write(self, event: Event) -> None:
        if not isinstance(event, Event):
            raise TypeError("Only allowlisted events can be logged")
        record = logging.LogRecord("researchmail", logging.INFO, "", 0, event.value, (), None)
        self.handler.handle(record)

    def close(self) -> None:
        self.handler.close()
