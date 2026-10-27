import imaplib
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

from researchmail.mail.imap import IMAPSession, MailSession, SessionFactory
from researchmail.mail.mime import MAX_MESSAGE_BYTES, content_hash, parse_message
from researchmail.mail.models import (
    AccountConfig,
    Failure,
    Folder,
    MailError,
    ParsedMessage,
    SyncResult,
)
from researchmail.security.credentials import CredentialStore, MacKeychain
from researchmail.storage.database import Database, StorageError
from researchmail.storage.mail_repository import MailRepository


@dataclass(frozen=True)
class Outcome:
    value: object = None
    error: Failure | None = None


def safely(operation: Callable[[], object]) -> Outcome:
    try:
        return Outcome(operation())
    except MailError as exc:
        return Outcome(error=exc.code)
    except StorageError:
        return Outcome(error=Failure.STORAGE)
    except (ValueError, StopIteration):
        return Outcome(error=Failure.CONFIG)


class MailService:
    def __init__(
        self,
        database: Database,
        vault: CredentialStore | None = None,
        factory: SessionFactory = IMAPSession,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repository = MailRepository(database)
        self.vault = vault if vault is not None else MacKeychain()
        self.factory = factory
        self.sleep = sleep
        self._lock = threading.Lock()

    def save_account(self, config: AccountConfig, secret: str, account_id: int | None) -> int:
        if not self._lock.acquire(blocking=False):
            raise MailError(Failure.BUSY)
        try:
            previous = self.repository.account(account_id) if account_id is not None else None
            if any(
                a.config.email.casefold() == config.email.casefold() and a.id != account_id
                for a in self.repository.accounts()
            ):
                raise MailError(Failure.DUPLICATE)
            if previous is not None:
                identity_changed = (
                    previous.config.email,
                    previous.config.imap_host,
                    previous.config.imap_port,
                ) != (config.email, config.imap_host, config.imap_port)
                if identity_changed and self.repository.has_sync_state(previous.id):
                    raise MailError(Failure.IDENTITY)
            reference = previous.credential_ref if previous is not None else None
            if not secret and (
                not reference or (previous and previous.config.email != config.email)
            ):
                raise MailError(Failure.CONFIG)
            new_reference = "imap-" + uuid4().hex if secret else reference
            if new_reference is None:
                raise MailError(Failure.CONFIG)
            if secret:
                self.vault.set(new_reference, secret)
            try:
                result = self.repository.save_account(config, new_reference, account_id)
            except Exception:
                if secret:
                    with suppress(MailError):
                        self.vault.delete(new_reference)
                raise
            if secret and reference:
                # A Keychain denial during cleanup leaves an inaccessible orphan, never plaintext.
                with suppress(MailError):
                    self.vault.delete(reference)
            return result
        finally:
            self._lock.release()

    def _connected(self, account_id: int, operation: Callable[[MailSession], object]) -> object:
        if not self._lock.acquire(blocking=False):
            raise MailError(Failure.BUSY)
        try:
            account = self.repository.account(account_id)
            if not account.credential_ref:
                raise MailError(Failure.KEYCHAIN)
            secret = self.vault.get(account.credential_ref)
            for attempt in range(3):
                session = None
                try:
                    session = self.factory(account.config, secret)
                    return operation(session)
                except MailError:
                    raise
                except (OSError, imaplib.IMAP4.abort):
                    if attempt == 2:
                        raise MailError(Failure.NETWORK) from None
                except imaplib.IMAP4.error:
                    raise MailError(Failure.PROTOCOL) from None
                finally:
                    if session is not None:
                        session.close()
                self.sleep(0.5 * (2**attempt))
            raise MailError(Failure.NETWORK)
        finally:
            self._lock.release()

    def test_connection(self, account_id: int) -> list[Folder]:
        def test(session: MailSession) -> list[Folder]:
            folders = session.folders()
            self.repository.save_folders(account_id, folders)
            return folders

        result = self._connected(account_id, test)
        if not isinstance(result, list):
            raise MailError(Failure.PROTOCOL)
        return result

    def sync(
        self,
        account_id: int,
        folder: str,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
        limit: int = 100,
    ) -> SyncResult:
        imported = 0
        changed = False
        processed_total = 0
        batch_limit = max(1, min(limit, 100))

        def synchronize(session: MailSession) -> SyncResult:
            nonlocal imported, changed, processed_total
            validity = session.select(folder)
            after, reset = self.repository.start_cursor(account_id, folder, validity)
            changed = changed or reset
            uids = session.uids(after)
            selected = uids[: max(0, batch_limit - processed_total)]
            processed = 0
            for uid in selected:
                if cancel is not None and cancel.is_set():
                    break
                size, raw = session.fetch(uid)
                parsed = parse_message(raw) if raw is not None else None
                if size > MAX_MESSAGE_BYTES:
                    parsed = ParsedMessage(
                        subject="邮件超过 20 MiB",
                        body="仅缓存 UID 与大小；正文及附件未下载。",
                        parse_status="oversized",
                    )
                added = self.repository.store_message(
                    account_id,
                    folder,
                    validity,
                    uid,
                    parsed,
                    size,
                    content_hash(raw) if raw is not None else None,
                )
                imported += int(added)
                processed += 1
                processed_total += 1
                if progress is not None:
                    progress(
                        processed_total, min(batch_limit, len(uids) + processed_total - processed)
                    )
            self.repository.finish_cursor(account_id, folder)
            return SyncResult(
                imported, len(uids) - processed, cancel is not None and cancel.is_set(), changed
            )

        try:
            result = self._connected(account_id, synchronize)
        except Exception:
            with suppress(StorageError):
                self.repository.finish_cursor(account_id, folder, error=True)
            raise
        if not isinstance(result, SyncResult):
            raise MailError(Failure.PROTOCOL)
        return result
