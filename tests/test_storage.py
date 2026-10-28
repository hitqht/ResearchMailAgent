import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from researchmail.config import AppPaths
from researchmail.storage.database import (
    Database,
    Migration,
    StorageError,
    packaged_migrations,
    statements,
)


def test_initialization_idempotency_permissions_and_schema(paths: AppPaths) -> None:
    db = Database(paths.database)
    assert db.initialize() == len(packaged_migrations())
    assert db.initialize() == len(packaged_migrations())
    assert paths.database.stat().st_mode & 0o777 == 0o600
    with db.connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "accounts",
            "messages",
            "analyses",
            "tasks",
            "drafts",
            "sync_cursors",
            "audit_events",
            "schema_migrations",
            "app_settings",
        } <= tables
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(
            packaged_migrations()
        )


def test_upgrade_preserves_existing_data(paths: AppPaths) -> None:
    db = Database(paths.database)
    migrations = packaged_migrations()
    db.initialize(migrations[:1])
    with db.transaction() as conn:
        conn.execute("INSERT INTO accounts(email) VALUES (?)", ("fixture@example.invalid",))
    assert db.initialize() == len(packaged_migrations())
    with db.connection() as conn:
        assert conn.execute("SELECT email FROM accounts").fetchone()[0] == "fixture@example.invalid"


def test_atomic_failed_migration_and_retry(paths: AppPaths) -> None:
    db = Database(paths.database)
    db.initialize()
    broken = Migration(
        len(packaged_migrations()) + 1,
        "next_broken.sql",
        "CREATE TABLE attempt(id);\nINVALID SQL;\n",
    )
    with pytest.raises(StorageError):
        db.initialize((*packaged_migrations(), broken))
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(
            packaged_migrations()
        )
        assert (
            conn.execute("SELECT name FROM sqlite_master WHERE name='attempt'").fetchone() is None
        )
    repaired = Migration(
        len(packaged_migrations()) + 1, "next_fixed.sql", "CREATE TABLE attempt(id INTEGER);\n"
    )
    assert db.initialize((*packaged_migrations(), repaired)) == len(packaged_migrations()) + 1
    with pytest.raises(StorageError, match="newer"):
        db.initialize()


def test_history_tamper_and_invalid_plan(paths: AppPaths) -> None:
    db = Database(paths.database)
    with pytest.raises(StorageError, match="sequence"):
        db.initialize((Migration(2, "bad", ""),))
    db.initialize()
    with db.transaction() as conn:
        conn.execute("UPDATE schema_migrations SET checksum=? WHERE version=?", ("changed", 1))
    with pytest.raises(StorageError, match="mismatch"):
        db.initialize()


def test_transaction_rollback_and_parameter_binding(paths: AppPaths) -> None:
    db = Database(paths.database)
    db.initialize()
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO accounts(email) VALUES (?)", ("fixture@example.invalid",))
        raise RuntimeError("simulated interruption")
    hostile = "'); DROP TABLE accounts; --"
    with db.transaction() as conn:
        conn.execute("INSERT INTO accounts(email) VALUES (?)", (hostile,))
    with db.connection() as conn:
        assert [r[0] for r in conn.execute("SELECT email FROM accounts")] == [hostile]


def test_uid_identity_and_foreign_keys(paths: AppPaths) -> None:
    db = Database(paths.database)
    db.initialize()
    with db.transaction() as conn:
        conn.execute("INSERT INTO accounts(id,email) VALUES (?,?)", (1, "fixture@example.invalid"))
        conn.execute("INSERT INTO accounts(id,email) VALUES (?,?)", (2, "second@example.invalid"))
        for identity in (
            (1, "INBOX", 1, 1),
            (1, "INBOX", 2, 1),
            (1, "Archive", 1, 1),
            (2, "INBOX", 1, 1),
        ):
            conn.execute(
                "INSERT INTO messages(account_id,folder,uidvalidity,uid) VALUES (?,?,?,?)", identity
            )
    with pytest.raises(StorageError) as duplicate, db.transaction() as conn:
        conn.execute(
            "INSERT INTO messages(account_id,folder,uidvalidity,uid) VALUES (?,?,?,?)",
            (1, "INBOX", 1, 1),
        )
    assert isinstance(duplicate.value.__cause__, sqlite3.IntegrityError)
    with pytest.raises(StorageError), db.transaction() as conn:
        conn.execute(
            "INSERT INTO messages(account_id,folder,uidvalidity,uid) VALUES (?,?,?,?)",
            (999, "INBOX", 1, 1),
        )


def test_concurrent_connections_and_initialization(paths: AppPaths) -> None:
    db = Database(paths.database)
    db.initialize()

    def write(index: int) -> None:
        db.initialize()
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO accounts(email) VALUES (?)", (f"user{index}@example.invalid",)
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 12


def test_corruption_preserved(paths: AppPaths) -> None:
    content = b"deliberately corrupted database fixture"
    paths.database.write_bytes(content)
    with pytest.raises(StorageError):
        Database(paths.database).initialize()
    assert paths.database.read_bytes() == content


def test_backup_is_consistent_and_never_overwrites(paths: AppPaths, tmp_path: Path) -> None:
    db = Database(paths.database)
    db.initialize()
    with db.transaction() as conn:
        conn.execute("INSERT INTO accounts(email) VALUES (?)", ("backup@example.invalid",))
        destination = tmp_path / "backup.sqlite3"
        db.backup(destination)
        # The uncommitted write must not leak into the backup.
    with Database(destination).connection() as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0
    assert destination.stat().st_mode & 0o777 == 0o600
    with pytest.raises(StorageError):
        db.backup(destination)
    with pytest.raises(StorageError):
        db.backup(paths.database)


def test_database_symlink_is_rejected(paths: AppPaths, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("unchanged")
    paths.database.symlink_to(target)
    with pytest.raises(StorageError):
        Database(paths.database).initialize()
    assert target.read_text() == "unchanged"


def test_incomplete_migration_rejected() -> None:
    with pytest.raises(StorageError, match="Incomplete"):
        list(statements("CREATE TABLE unfinished(id INTEGER)"))


def test_backup_failure_cleans_only_new_destination(paths: AppPaths, tmp_path: Path) -> None:
    paths.database.write_bytes(b"corrupt fixture")
    destination = tmp_path / "failed.sqlite3"
    with pytest.raises(StorageError):
        Database(paths.database).backup(destination)
    assert not destination.exists()
    assert paths.database.read_bytes() == b"corrupt fixture"
