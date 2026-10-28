import imaplib
import ssl
from unittest.mock import MagicMock

import pytest

from researchmail.mail import imap
from researchmail.mail.mime import MAX_MESSAGE_BYTES
from researchmail.mail.models import AccountConfig, Failure, MailError


@pytest.fixture
def adapter(monkeypatch):
    client = MagicMock()
    client.capabilities = ("IMAP4REV1", "ID")
    client.login.return_value = ("OK", [b"authenticated"])
    client.xatom.return_value = ("OK", [b"ID NIL"])
    client.list.return_value = ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])
    client.select.return_value = ("OK", [b"2"])
    client.response.return_value = ("UIDVALIDITY", [b"1234"])
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(imap, "BoundedIMAP", factory)
    session = imap.IMAPSession(AccountConfig(email="fixture@example.invalid"), "synthetic-only")
    return session, client, factory


def test_ssl_id_readonly_fetch_and_logout(adapter) -> None:
    session, client, factory = adapter
    context = factory.call_args.kwargs["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    client.xatom.assert_called_once()
    assert client.xatom.call_args.args[0] == "ID"
    assert session.select("INBOX") == 1234
    client.select.assert_called_with('"INBOX"', readonly=True)
    assert session.folders()[0].wire_name == "INBOX"
    client.uid.side_effect = [
        ("OK", [b"10 9 10 8"]),
        ("OK", [b"1 (RFC822.SIZE 5 UID 10)"]),
        ("OK", [(b"1 (UID 10 BODY[]<0> {5}", b"hello"), b")"]),
    ]
    assert session.uids(8) == [9, 10]
    assert session.fetch(10) == (5, b"hello")
    assert "BODY.PEEK" in client.uid.call_args.args[-1]
    session.close()
    client.logout.assert_called_once()
    client.close.assert_not_called()
    client.store.assert_not_called()
    client.expunge.assert_not_called()
    client.append.assert_not_called()


@pytest.mark.parametrize("values", [[None], [b"0"], [b"no-number"]])
def test_missing_or_bad_uidvalidity_is_rejected(adapter, values) -> None:
    session, client, _ = adapter
    client.response.return_value = ("UIDVALIDITY", values)
    with pytest.raises(MailError):
        session.select("INBOX")


def test_last_uid_search_corner_and_oversize_skip(adapter) -> None:
    session, client, _ = adapter
    client.uid.return_value = ("OK", [b"10"])
    assert session.uids(10) == []
    client.uid.return_value = ("OK", [f"1 (UID 1 RFC822.SIZE {MAX_MESSAGE_BYTES + 1})".encode()])
    assert session.fetch(1) == (MAX_MESSAGE_BYTES + 1, None)
    assert client.uid.call_args.args[-1] == "(UID RFC822.SIZE)"


def test_bad_fetch_uid_length_and_expunge(adapter) -> None:
    session, client, _ = adapter
    client.uid.return_value = ("OK", [None])
    assert session.fetch(1) == (0, None)
    client.uid.side_effect = [("OK", [b"1 (UID 2 RFC822.SIZE 5)"])]
    with pytest.raises(MailError):
        session.fetch(1)
    client.uid.side_effect = [
        ("OK", [b"1 (UID 1 RFC822.SIZE 5)"]),
        ("OK", [(b"1 (UID 1 BODY[] {4}", b"bad")]),
    ]
    with pytest.raises(MailError):
        session.fetch(1)


def test_auth_error_never_exposes_server_message(monkeypatch) -> None:
    client = MagicMock()
    client.login.side_effect = imaplib.IMAP4.error("server includes private fixture")
    monkeypatch.setattr(imap, "BoundedIMAP", lambda *args, **kwargs: client)
    with pytest.raises(MailError) as failure:
        imap.IMAPSession(AccountConfig(email="fixture@example.invalid"), "synthetic-only")
    assert failure.value.code == Failure.AUTH
    assert "private" not in str(failure.value)
    client.logout.assert_called_once()


def test_folder_utf7_quoted_literal_noselect_and_injection() -> None:
    folders = imap.parse_folders(
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\NoSelect) "/" "Archive"',
            (b'() "/" {5}', b"INBOX"),
            b'() "/" "&T2BZfQ-"',
        ]
    )
    assert not folders[1].selectable
    assert folders[3].display_name == "你好"
    assert imap.decode_folder("A&-B") == "A&B"
    for value in ("INBOX\r\nDELETE INBOX", "", "中文"):
        with pytest.raises(MailError):
            imap.quote_mailbox(value)
    assert imap.quote_mailbox('a"b\\c') == '"a\\"b\\\\c"'
    with pytest.raises(MailError):
        imap.parse_folders([b"invalid LIST response"])


def test_literal_bound_before_allocation() -> None:
    client = object.__new__(imap.BoundedIMAP)
    with pytest.raises(MailError):
        client.read(MAX_MESSAGE_BYTES + 2)


def test_server_size_discrepancy_with_valid_complete_literal(adapter):
    session, client, _ = adapter
    # Reproduces the observed 163 discrepancy using synthetic content only.
    client.uid.side_effect = [
        ("OK", [b"1 (UID 1 RFC822.SIZE 9)"]),
        ("OK", [(b"1 (UID 1 BODY[]<0> {5}", b"hello"), b")"]),
    ]
    assert session.fetch(1) == (5, b"hello")


def test_uid_may_follow_the_body_literal(adapter):
    session, client, _ = adapter
    client.uid.side_effect = [
        ("OK", [b"1 (UID 1 RFC822.SIZE 5)"]),
        ("OK", [(b"1 (BODY[]<0> {5}", b"hello"), b" UID 1)"]),
    ]
    assert session.fetch(1) == (5, b"hello")
