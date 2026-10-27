from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from researchmail.config import AppPaths
from researchmail.storage.database import Database


@dataclass(frozen=True)
class WorkspaceState:
    schema_version: int
    onboarding_completed: bool


class WorkspaceService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.database = Database(paths.database)

    def initialize(self) -> WorkspaceState:
        self.paths.prepare()
        version = self.database.initialize()
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", ("onboarding_completed",)
            ).fetchone()
        return WorkspaceState(version, row is not None and row["value"] == "true")

    def complete_onboarding(self) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                ("onboarding_completed", "true"),
            )
            conn.execute(
                "INSERT INTO audit_events(event,outcome) VALUES (?,?)",
                ("onboarding_completed", "success"),
            )

    def backup(self) -> Path:
        directory = self.paths.data / "backups"
        if directory.is_symlink():
            raise OSError("Backup directory must not be a symbolic link")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = directory / f"researchmail-{timestamp}-{uuid4().hex[:8]}.sqlite3"
        self.database.backup(destination)
        return destination
