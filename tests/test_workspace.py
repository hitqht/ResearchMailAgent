from pathlib import Path

import pytest

from researchmail.config import AppPaths
from researchmail.eventlog import Event, EventLog
from researchmail.services.workspace import WorkspaceService
from researchmail.storage.database import Database


def test_paths_and_private_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    paths = AppPaths.default()
    assert (
        paths.database
        == tmp_path / "Library/Application Support/ResearchMailAgent/researchmail.sqlite3"
    )
    assert paths.logs == tmp_path / "Library/Logs/ResearchMailAgent"
    paths.prepare()
    paths.prepare()
    assert paths.data.stat().st_mode & 0o777 == 0o700
    assert paths.logs.stat().st_mode & 0o777 == 0o700


def test_path_symlink_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        AppPaths(link, tmp_path / "logs").prepare()


def test_first_run_persistence_and_backup(service: WorkspaceService) -> None:
    assert not service.initialize().onboarding_completed
    service.complete_onboarding()
    assert WorkspaceService(service.paths).initialize().onboarding_completed
    backup = service.backup()
    assert backup.parent == service.paths.data / "backups"
    with Database(backup).connection() as conn:
        assert conn.execute("SELECT value FROM app_settings").fetchone()[0] == "true"
        assert (
            conn.execute("SELECT event FROM audit_events").fetchone()[0] == "onboarding_completed"
        )


def test_credentials_have_no_settings_slot(service: WorkspaceService) -> None:
    from researchmail.storage.database import StorageError

    with pytest.raises(StorageError), service.database.transaction() as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES (?,?)", ("api_key", "fixture"))


def test_event_log_rejects_arbitrary_text(paths: AppPaths) -> None:
    log = EventLog(paths.logs)
    log.write(Event.STARTUP_OK)
    with pytest.raises(TypeError):
        log.write("mail body or credential must never be logged")  # type: ignore[arg-type]
    log.close()
    content = (paths.logs / "events.log").read_text()
    assert "startup_ok" in content
    assert "credential" not in content
    assert "mail body" not in content


def test_log_symlink_rejected(paths: AppPaths, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("original")
    (paths.logs / "events.log").symlink_to(target)
    with pytest.raises(OSError):
        EventLog(paths.logs)
    assert target.read_text() == "original"
