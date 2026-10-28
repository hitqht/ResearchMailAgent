import fcntl
import json
import os
import secrets
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from email.utils import getaddresses
from typing import Protocol
from uuid import uuid4

from researchmail.drafts.models import DraftContent, DraftError, DraftStatus, SendPreview, address
from researchmail.mail.models import Account, MailError
from researchmail.mail.smtp import SMTPTransport
from researchmail.security.credentials import CredentialStore, MacKeychain
from researchmail.services.ai_service import AIService
from researchmail.storage.database import Database, StorageError
from researchmail.storage.draft_repository import DraftRepository
from researchmail.storage.mail_repository import MailRepository


class Transport(Protocol):
    def test_connection(self, account: Account, secret: str) -> None: ...

    def send(self, preview: SendPreview, secret: str, before_data: Callable[[], None]) -> None: ...


class DraftService:
    def __init__(
        self,
        database: Database,
        vault: CredentialStore | None = None,
        transport: Transport | None = None,
        ai: AIService | None = None,
    ) -> None:
        self.repository = DraftRepository(database)
        self.vault = vault if vault is not None else MacKeychain()
        self.transport = transport if transport is not None else SMTPTransport()
        self.ai = ai if ai is not None else AIService(database)
        self._tokens: dict[str, tuple[int, str, float]] = {}
        self._mutex = threading.Lock()

    @contextmanager
    def _outbox_lock(self) -> Iterator[None]:
        path = self.repository.database.path.with_suffix(".outbox.lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DraftError("storage")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DraftError("busy") from None
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def recover_interrupted(self) -> int:
        try:
            with self._outbox_lock():
                return self.repository.recover()
        except DraftError as error:
            if error.code == "busy":
                return 0
            raise

    def test_smtp(self, account_id: int) -> None:
        with self._outbox_lock():
            try:
                account = MailRepository(self.repository.database).account(account_id)
                secret = self.vault.get(account.credential_ref or "")
            except (MailError, KeyError):
                raise DraftError("keychain") from None
            except StopIteration:
                raise DraftError("missing") from None
            self.transport.test_connection(account, secret)

    def create_reply(
        self, message_id: int, intent: str, model_id: int | None = None, use_model: bool = False
    ) -> int:
        source = self.ai.repository.source(message_id)
        data = json.loads(source)
        with self.repository.database.connection() as conn:
            row = conn.execute(
                "SELECT account_id FROM messages WHERE id=?", (message_id,)
            ).fetchone()
        if row is None:
            raise DraftError("missing")
        recipients: tuple[str, ...] = ()
        candidates = getaddresses([data["sender"]])
        if len(candidates) == 1:
            with suppress(ValueError):
                recipients = (address(candidates[0][1]),)
        subject = data["subject"]
        subject = subject if subject.lower().startswith("re:") else "Re: " + subject
        subject = " ".join(subject.split())[:1000]
        body = intent
        if use_model:
            generated = self.ai.generate_local_reply(message_id, intent, model_id)
            subject, body = generated.subject, generated.body
        return self.repository.create(
            DraftContent(
                account_id=row[0],
                message_id=message_id,
                recipients=recipients,
                subject=subject,
                body=body,
            )
        )

    def authorize_send(self, preview: SendPreview) -> str:
        current = self.repository.preview(preview.draft.id)
        if current.digest != preview.digest:
            raise DraftError("stale")
        if (
            current.draft.status != DraftStatus.APPROVED
            or current.draft.approved_digest != current.digest
        ):
            raise DraftError("state")
        token = secrets.token_urlsafe(32)
        with self._mutex:
            self._tokens = {k: v for k, v in self._tokens.items() if v[2] > time.monotonic()}
            self._tokens[token] = (current.draft.id, current.digest, time.monotonic() + 300)
        return token

    def _denied(self, draft_id: int) -> None:
        with self.repository.database.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) "
                "VALUES ('send_denied','draft',?,'denied')",
                (draft_id,),
            )

    def send_approved(self, draft_id: int, token: str) -> DraftStatus:
        with self._mutex:
            grant = self._tokens.pop(token, None)
        if grant is None or grant[0] != draft_id or grant[2] <= time.monotonic():
            self._denied(draft_id)
            raise DraftError("denied")
        with self._outbox_lock():
            attempt = uuid4().hex
            try:
                preview = self.repository.claim(draft_id, grant[1], attempt)
            except DraftError:
                self._denied(draft_id)
                raise
            started = False

            def before_data() -> None:
                nonlocal started
                self.repository.data_started(attempt)
                started = True

            try:
                secret = self.vault.get(preview.account.credential_ref or "")
                self.transport.send(preview, secret, before_data)
            except Exception as error:
                if isinstance(error, MailError):
                    code = "keychain"
                elif isinstance(error, DraftError):
                    code = error.code
                elif isinstance(error, StorageError):
                    code = "storage"
                else:
                    code = "uncertain" if started else "network"
                status = (
                    DraftStatus.UNCERTAIN
                    if code == "uncertain"
                    or (started and code not in {"rejected", "recipient", "auth"})
                    else DraftStatus.FAILED
                )
                try:
                    self.repository.finish(
                        attempt, status, "uncertain" if status == DraftStatus.UNCERTAIN else code
                    )
                except StorageError:
                    raise DraftError("uncertain") from None
                raise DraftError("uncertain" if status == DraftStatus.UNCERTAIN else code) from None
            try:
                self.repository.finish(attempt, DraftStatus.SENT)
            except StorageError:
                raise DraftError("uncertain") from None
            return DraftStatus.SENT
