"""Never discover or fall back to plaintext keyring backends."""

from importlib import import_module
from typing import Protocol, cast

from researchmail.mail.models import Failure, MailError

SERVICE = "ResearchMailAgent.IMAP"


class CredentialStore(Protocol):
    def get(self, reference: str) -> str: ...
    def set(self, reference: str, secret: str) -> None: ...
    def delete(self, reference: str) -> None: ...


class KeychainBackend(Protocol):
    priority: int

    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class MacKeychain:
    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    def _backend(self) -> KeychainBackend:
        backend = cast(KeychainBackend, import_module("keyring.backends.macOS").Keyring())
        if backend.priority <= 0:
            raise MailError(Failure.KEYCHAIN)
        return backend

    def get(self, reference: str) -> str:
        try:
            value = self._backend().get_password(self.service, reference)
            if not value:
                raise MailError(Failure.KEYCHAIN)
            return value
        except Exception:
            raise MailError(Failure.KEYCHAIN) from None

    def set(self, reference: str, secret: str) -> None:
        try:
            self._backend().set_password(self.service, reference, secret)
        except Exception:
            raise MailError(Failure.KEYCHAIN) from None

    def delete(self, reference: str) -> None:
        try:
            self._backend().delete_password(self.service, reference)
        except Exception:
            raise MailError(Failure.KEYCHAIN) from None
