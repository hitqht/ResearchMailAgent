"""A deliberately read-only IMAP surface with TLS verification and bounded literals."""

import base64
import imaplib
import re
import ssl
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Protocol

from researchmail import __version__
from researchmail.mail.mime import MAX_MESSAGE_BYTES
from researchmail.mail.models import AccountConfig, Failure, Folder, MailError


class MailSession(Protocol):
    def folders(self) -> list[Folder]: ...
    def select(self, folder: str) -> int: ...
    def uids(self, after: int) -> list[int]: ...
    def fetch(self, uid: int) -> tuple[int, bytes | None]: ...
    def close(self) -> None: ...


SessionFactory = Callable[[AccountConfig, str], MailSession]


def decode_folder(value: str) -> str:
    def decode(match: re.Match[str]) -> str:
        token = match.group(1)
        if not token:
            return "&"
        return base64.b64decode(token.replace(",", "/") + "=" * (-len(token) % 4)).decode(
            "utf-16-be"
        )

    try:
        return re.sub(r"&([A-Za-z0-9+,]*)-", decode, value)
    except (ValueError, UnicodeError):
        return value


def quote_mailbox(value: str) -> str:
    if not value or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise MailError(Failure.PROTOCOL)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_folders(rows: Sequence[bytes | tuple[bytes, bytes] | None]) -> list[Folder]:
    folders: list[Folder] = []
    pattern = re.compile(rb'^\((.*?)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(.+)$')
    for row in rows:
        if row is None or row == b"":
            continue
        prefix, literal = row if isinstance(row, tuple) else (row, None)
        match = pattern.match(prefix)
        if not match:
            raise MailError(Failure.PROTOCOL)
        name = literal if literal is not None else match.group(2)
        if literal is None and name.startswith(b'"') and name.endswith(b'"'):
            name = re.sub(rb"\\(.)", rb"\1", name[1:-1])
        try:
            wire = name.decode("ascii")
        except UnicodeError:
            raise MailError(Failure.PROTOCOL) from None
        quote_mailbox(wire)
        folders.append(
            Folder(wire, decode_folder(wire), b"\\noselect" not in match.group(1).lower())
        )
    return folders


class BoundedIMAP(imaplib.IMAP4_SSL):
    def read(self, size: int) -> bytes:
        if size > MAX_MESSAGE_BYTES + 1:
            raise MailError(Failure.PROTOCOL)
        return super().read(size)


class IMAPSession:
    def __init__(self, config: AccountConfig, secret: str) -> None:
        self.client = BoundedIMAP(
            config.imap_host, config.imap_port, ssl_context=ssl.create_default_context(), timeout=20
        )
        self.client.debug = 0
        try:
            self.client.login(config.email, secret)
        except imaplib.IMAP4.abort:
            self.close()
            raise
        except imaplib.IMAP4.error:
            self.close()
            raise MailError(Failure.AUTH) from None
        except OSError:
            self.close()
            raise
        try:
            if "ID" in self.client.capabilities:
                status, _ = self.client.xatom(
                    "ID", f'("name" "ResearchMailAgent" "version" "{__version__}")'
                )
                self._ok(status)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _ok(status: str) -> None:
        if status != "OK":
            raise MailError(Failure.PROTOCOL)

    def folders(self) -> list[Folder]:
        status, data = self.client.list()
        self._ok(status)
        return parse_folders(data)

    def select(self, folder: str) -> int:
        status, _ = self.client.select(quote_mailbox(folder), readonly=True)
        self._ok(status)
        name, values = self.client.response("UIDVALIDITY")
        if name != "UIDVALIDITY" or not values or not values[0]:
            raise MailError(Failure.PROTOCOL)
        try:
            validity = int(values[0])
        except ValueError:
            raise MailError(Failure.PROTOCOL) from None
        if validity <= 0:
            raise MailError(Failure.PROTOCOL)
        return validity

    def uids(self, after: int) -> list[int]:
        status, data = self.client.uid("SEARCH", "UID", f"{after + 1}:*")
        self._ok(status)
        try:
            # IMAP N:* may return the last UID even when N is beyond the mailbox end.
            return sorted({int(value) for value in (data[0] or b"").split() if int(value) > after})
        except (ValueError, IndexError, TypeError):
            raise MailError(Failure.PROTOCOL) from None

    def fetch(self, uid: int) -> tuple[int, bytes | None]:
        status, metadata = self.client.uid("FETCH", str(uid), "(UID RFC822.SIZE)")
        self._ok(status)
        # A message can be expunged by another client between SEARCH and FETCH.
        if metadata == [None]:
            return 0, None
        fields = b" ".join(item for item in metadata if isinstance(item, bytes))
        found_uid = re.search(rb"\bUID (\d+)\b", fields, re.I)
        found_size = re.search(rb"\bRFC822\.SIZE (\d+)\b", fields, re.I)
        if not found_uid or not found_size or int(found_uid.group(1)) != uid:
            raise MailError(Failure.PROTOCOL)
        size = int(found_size.group(1))
        if size > MAX_MESSAGE_BYTES:
            return size, None
        status, data = self.client.uid(
            "FETCH", str(uid), f"(UID BODY.PEEK[]<0.{MAX_MESSAGE_BYTES + 1}>)"
        )
        self._ok(status)
        literals = [item for item in data if isinstance(item, tuple)]
        if not literals and data == [None]:
            return 0, None
        if len(literals) != 1:
            raise MailError(Failure.PROTOCOL)
        info, raw = literals[0]
        found_uid = re.search(rb"\bUID (\d+)\b", info)
        if not found_uid or int(found_uid.group(1)) != uid or len(raw) != size:
            raise MailError(Failure.PROTOCOL)
        return size, raw

    def close(self) -> None:
        # Never CLOSE: CLOSE may expunge a mailbox; LOGOUT does not.
        with suppress(OSError, imaplib.IMAP4.error, MailError):
            self.client.logout()
        with suppress(OSError):
            self.client.shutdown()
