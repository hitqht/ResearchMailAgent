"""One short-lived connection per operation, safe for worker threads.

Migration SQL is trusted, packaged code. All data values use bound parameters.
Existing/corrupt databases are preserved and never silently replaced.
"""

import hashlib
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


class StorageError(Exception):
    """A safe boundary error; raw SQLite messages are not shown or logged."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def packaged_migrations() -> tuple[Migration, ...]:
    root = files("researchmail.storage.migrations")
    return tuple(
        Migration(int(item.name.split("_")[0]), item.name, item.read_text(encoding="utf-8"))
        for item in sorted(root.iterdir(), key=lambda item: item.name)
        if item.name.endswith(".sql")
    )


def statements(script: str) -> Iterator[str]:
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ""
    if pending.strip():
        raise StorageError("Incomplete migration")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self.path.is_symlink():
            raise StorageError("Database must not be a symbolic link")
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            self.path.chmod(0o600)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
        except (sqlite3.Error, OSError) as exc:
            raise StorageError("Local storage operation failed") from exc
        finally:
            if conn is not None:
                conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def initialize(self, migrations: Sequence[Migration] | None = None) -> int:
        plan = tuple(migrations) if migrations is not None else packaged_migrations()
        if [item.version for item in plan] != list(range(1, len(plan) + 1)):
            raise StorageError("Migration sequence is invalid")
        with self.connection() as conn:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise StorageError("Database integrity check failed")
            if conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] != "wal":
                raise StorageError("WAL unavailable")
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, "
                "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            applied = conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
            if len(applied) > len(plan):
                raise StorageError("Database requires a newer application")
            for row, migration in zip(applied, plan, strict=False):
                if (row["version"], row["name"], row["checksum"]) != (
                    migration.version,
                    migration.name,
                    migration.checksum,
                ):
                    raise StorageError("Migration history mismatch")
            for migration in plan[len(applied) :]:
                for sql in statements(migration.sql):
                    conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version,name,checksum) VALUES (?,?,?)",
                    (migration.version, migration.name, migration.checksum),
                )
        return len(plan)

    def backup(self, destination: Path) -> None:
        """Consistent SQLite online backup, including committed WAL data; never overwrite."""
        if destination.resolve() == self.path.resolve():
            raise StorageError("Backup must use a separate file")
        try:
            with destination.open("xb"):
                destination.chmod(0o600)
        except OSError as exc:
            raise StorageError("Backup destination unavailable") from exc
        try:
            with self.connection() as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                    if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise StorageError("Backup integrity check failed")
                finally:
                    target.close()
        except (sqlite3.Error, StorageError) as exc:
            destination.unlink(missing_ok=True)
            raise StorageError("Backup failed; original data preserved") from exc
