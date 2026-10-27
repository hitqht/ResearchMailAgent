import imaplib
import threading

import pytest
from pydantic import ValidationError

from researchmail.mail.mime import MAX_MESSAGE_BYTES
from researchmail.mail.models import AccountConfig, Failure, MailError, ParsedMessage
from researchmail.services.mail_service import MailService, safely
from researchmail.services.workspace import WorkspaceService
from researchmail.storage.database import StorageError
from tests.fakes import FakeSession, MemoryVault


@pytest.fixture
def mail(service: WorkspaceService) -> tuple[MailService, MemoryVault, FakeSession, int]:
    vault = MemoryVault()
    session = FakeSession()
    mail = MailService(service.database, vault, lambda config, secret: session, lambda _: None)
    account_id = mail.save_account(
        AccountConfig(email="research@example.invalid"), "synthetic-only", None
    )
    return mail, vault, session, account_id


def test_account_key_rotation_and_no_database_secret(mail) -> None:
    service, vault, session, account_id = mail
    account = service.repository.account(account_id)
    original = account.credential_ref
    assert vault.values[original] == "synthetic-only"
    config = account.config.model_copy(update={"display_name": "实验邮箱", "sync_minutes": 5})
    service.save_account(config, "replacement-fixture", account_id)
    assert original not in vault.values
    updated = service.repository.account(account_id)
    assert vault.values[updated.credential_ref] == "replacement-fixture"
    service.save_account(config, "", account_id)
    assert service.repository.account(account_id) == updated
    assert b"synthetic-only" not in service.repository.database.path.read_bytes()
    with service.repository.database.connection() as conn:
        data = "\n".join(conn.iterdump())
    assert "replacement-fixture" not in data
    assert "synthetic-only" not in data


def test_save_rollback_cleans_new_key_and_retains_old(mail, monkeypatch) -> None:
    service, vault, session, account_id = mail
    account = service.repository.account(account_id)
    before = vault.values.copy()

    def fail(*args):
        raise StorageError("fixture failure")

    monkeypatch.setattr(service.repository, "save_account", fail)
    with pytest.raises(StorageError):
        service.save_account(account.config, "new-synthetic-value", account_id)
    assert vault.values == before
    assert service.repository.account(account_id) == account


def test_config_validation_and_missing_secret(mail) -> None:
    service, vault, session, account_id = mail
    for values in (
        {"email": "bad"},
        {"email": "x@y", "imap_host": "https://server"},
        {"email": "x@y", "sync_minutes": 1},
        {"email": "x@y", "imap_port": 0},
    ):
        with pytest.raises(ValidationError):
            AccountConfig(**values)
    with pytest.raises(MailError):
        service.save_account(AccountConfig(email="new@example.invalid"), "", None)
    with pytest.raises(MailError):
        service.save_account(AccountConfig(email="new@example.invalid"), "", account_id)


def test_incremental_dedupe_and_uidvalidity_preserves_history(mail) -> None:
    service, vault, session, account_id = mail
    assert len(service.test_connection(account_id)) == 3
    assert len(service.repository.folders(account_id)) == 3
    assert service.sync(account_id, "INBOX").imported == 2
    assert service.sync(account_id, "INBOX").imported == 0
    assert session.fetched == [1, 2]
    session.content[5] = b"Subject: Added\r\n\r\nNew"
    assert service.sync(account_id, "INBOX").imported == 1
    assert [m.uid for m in service.repository.messages(account_id, "INBOX")] == [5, 2, 1]
    session.validity = 20
    result = service.sync(account_id, "INBOX")
    assert result.uidvalidity_changed
    assert result.imported == 3
    with service.repository.database.connection() as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 6
    assert len(service.repository.messages(account_id, "INBOX")) == 3
    assert len(service.repository.messages(account_id, "INBOX", "REVISION")) == 1
    assert service.repository.messages(account_id, "INBOX", "';DROP TABLE messages;--") == []


def test_retry_resumes_after_last_committed_uid(mail, monkeypatch) -> None:
    service, vault, session, account_id = mail
    original = session.fetch
    failed = False

    def fetch(uid):
        nonlocal failed
        if uid == 2 and not failed:
            failed = True
            raise OSError("sensitive-server-fixture")
        return original(uid)

    monkeypatch.setattr(session, "fetch", fetch)
    result = service.sync(account_id, "INBOX")
    assert result.imported == 2
    assert session.fetched == [1, 2]
    assert session.closed == 2


def test_auth_never_retries_and_network_retries_three_times(mail) -> None:
    service, vault, session, account_id = mail
    calls = []

    def auth(config, secret):
        calls.append(1)
        raise MailError(Failure.AUTH)

    service.factory = auth
    result = safely(lambda: service.test_connection(account_id))
    assert result.error == Failure.AUTH and len(calls) == 1

    def network(config, secret):
        calls.append(1)
        raise imaplib.IMAP4.abort("synthetic server disconnect")

    calls.clear()
    service.factory = network
    result = safely(lambda: service.sync(account_id, "INBOX"))
    assert result.error == Failure.NETWORK and len(calls) == 3


def test_batch_cancel_disappearing_and_oversized(mail, monkeypatch) -> None:
    service, vault, session, account_id = mail
    session.content = {i: b"Subject: synthetic\r\n\r\nbody" for i in range(1, 106)}
    progress = []
    result = service.sync(
        account_id, "INBOX", progress=lambda done, total: progress.append((done, total))
    )
    assert result.imported == 100 and result.remaining == 5
    assert progress[-1] == (100, 100)
    cancel = threading.Event()
    cancel.set()
    assert service.sync(account_id, "INBOX", cancel).cancelled
    assert len(session.fetched) == 100

    def special(uid):
        return (MAX_MESSAGE_BYTES + 1, None) if uid == 101 else (0, None)

    monkeypatch.setattr(session, "fetch", special)
    result = service.sync(account_id, "INBOX")
    assert result.imported == 1 and result.remaining == 0
    messages = service.repository.messages(account_id, "INBOX")
    assert messages[0].parsed.parse_status == "oversized"
    assert service.sync(account_id, "INBOX").imported == 0


def test_keychain_failure_is_fail_closed(mail, monkeypatch) -> None:
    service, vault, session, account_id = mail

    def denied(ref):
        raise MailError(Failure.KEYCHAIN)

    monkeypatch.setattr(vault, "get", denied)
    assert safely(lambda: service.sync(account_id, "INBOX")).error == Failure.KEYCHAIN
    assert session.closed == 0


def test_repository_cursor_race_rolls_back_message(mail) -> None:
    service, vault, session, account_id = mail
    repository = service.repository
    repository.start_cursor(account_id, "INBOX", 10)
    with pytest.raises(ValueError):
        repository.store_message(
            account_id, "INBOX", 20, 1, ParsedMessage(subject="fixture"), 10, None
        )
    with repository.database.connection() as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_lock_prevents_parallel_operations(mail) -> None:
    service, vault, session, account_id = mail
    with service._lock, pytest.raises(MailError) as failure:
        service.save_account(AccountConfig(email="new@example.invalid"), "fixture", None)
    assert failure.value.code == Failure.BUSY


def test_identity_changes_after_sync_do_not_mix_cache(mail) -> None:
    service, vault, session, account_id = mail
    service.sync(account_id, "INBOX")
    original = service.repository.account(account_id)
    changed = original.config.model_copy(update={"imap_host": "another.example.invalid"})
    assert safely(lambda: service.save_account(changed, "", account_id)).error == Failure.IDENTITY
    assert service.repository.account(account_id) == original
    assert (
        safely(lambda: service.save_account(original.config, "fixture", None)).error
        == Failure.DUPLICATE
    )


def test_upgrade_m0_keeps_account_and_cursor_data(paths) -> None:
    from researchmail.storage.database import Database, packaged_migrations

    db = Database(paths.database)
    db.initialize(packaged_migrations()[:2])
    with db.transaction() as conn:
        conn.execute("INSERT INTO accounts(id,email) VALUES (?,?)", (1, "legacy@example.invalid"))
        conn.execute(
            "INSERT INTO sync_cursors(account_id,folder,uidvalidity,last_uid) VALUES (?,?,?,?)",
            (1, "INBOX", 7, 42),
        )
    assert db.initialize() == 3
    with db.connection() as conn:
        account = conn.execute("SELECT * FROM accounts").fetchone()
        assert account["email"] == "legacy@example.invalid"
        assert account["credential_ref"] is None
        assert conn.execute("SELECT last_uid FROM sync_cursors").fetchone()[0] == 42
