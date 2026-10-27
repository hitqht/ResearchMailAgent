from types import SimpleNamespace

import pytest

from researchmail.mail.models import Failure, MailError
from researchmail.security import credentials


class Backend:
    priority = 5

    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        del self.values[(service, username)]


def test_only_macos_backend_and_sanitized_denial(monkeypatch) -> None:
    backend = Backend()
    imported = []

    def load(name):
        imported.append(name)
        return SimpleNamespace(Keyring=lambda: backend)

    monkeypatch.setattr(credentials, "import_module", load)
    vault = credentials.MacKeychain()
    vault.set("local-reference", "synthetic-only")
    assert vault.get("local-reference") == "synthetic-only"
    vault.delete("local-reference")
    with pytest.raises(MailError) as failure:
        vault.get("local-reference")
    assert failure.value.code == Failure.KEYCHAIN
    backend.priority = 0
    with pytest.raises(MailError):
        vault.set("reference", "synthetic-only")
    with pytest.raises(MailError):
        vault.delete("reference")
    assert set(imported) == {"keyring.backends.macOS"}
