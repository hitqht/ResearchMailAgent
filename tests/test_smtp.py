import smtplib
import ssl
from unittest.mock import MagicMock

import pytest

from researchmail.drafts.models import DraftError
from researchmail.mail.smtp import SMTPTransport, wire_message
from tests.test_drafts import approve, create


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    client.mail.return_value = (250, b"OK")
    client.rcpt.return_value = (250, b"OK")
    client.data.return_value = (250, b"accepted")
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("researchmail.mail.smtp.smtplib.SMTP_SSL", factory)
    return client, factory


def test_smtp_ssl_full_envelope_and_plain_message(drafts, client):
    mock, factory = client
    preview = approve(drafts, create(drafts))
    called = []
    SMTPTransport().send(preview, "synthetic-smtp", lambda: called.append(True))
    context = factory.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert factory.call_args.args == ("smtp.163.com", 465)
    assert mock.set_debuglevel.call_args.args == (0,)
    assert called == [True]
    payload = mock.data.call_args.args[0]
    assert payload == wire_message(preview) and b"\r\nMessage-ID:" in payload
    assert b"Bcc:" not in payload and b"Content-Type: text/plain" in payload
    mock.quit.assert_called_once()


def test_partial_recipient_refusal_aborts_before_data(drafts, client):
    mock, _ = client
    draft = create(drafts)
    d = drafts.repository.get(draft)
    drafts.repository.save(
        draft,
        d.content.model_copy(update={"recipients": ("a@example.invalid", "b@example.invalid")}),
        d.revision,
    )
    preview = approve(drafts, draft)
    mock.rcpt.side_effect = [(250, b"OK"), (550, b"private response")]
    called = []
    with pytest.raises(DraftError, match="recipient"):
        SMTPTransport().send(preview, "synthetic", lambda: called.append(True))
    assert not called
    mock.data.assert_not_called()
    mock.rset.assert_called_once()


@pytest.mark.parametrize(
    "phase,exception,code",
    [
        ("login", smtplib.SMTPAuthenticationError(535, b"private"), "auth"),
        ("mail", TimeoutError("private"), "network"),
        ("data", TimeoutError("private"), "uncertain"),
        ("data", smtplib.SMTPDataError(554, b"private"), "rejected"),
    ],
)
def test_smtp_errors_and_uncertainty(drafts, client, phase, exception, code):
    mock, _ = client
    getattr(mock, phase).side_effect = exception
    with pytest.raises(DraftError, match=code) as error:
        SMTPTransport().send(approve(drafts, create(drafts)), "synthetic", lambda: None)
    assert "private" not in str(error.value)


def test_quit_timeout_does_not_undo_acceptance(drafts, client):
    mock, _ = client
    mock.quit.side_effect = TimeoutError("private")
    SMTPTransport().send(approve(drafts, create(drafts)), "synthetic", lambda: None)
    mock.data.assert_called_once()
    mock.close.assert_called_once()


def test_connection_only_never_submits_envelope(drafts, client):
    mock, _ = client
    preview = approve(drafts, create(drafts))
    SMTPTransport().test_connection(preview.account, "synthetic")
    mock.login.assert_called_once()
    mock.mail.assert_not_called()
    mock.rcpt.assert_not_called()
    mock.data.assert_not_called()


@pytest.mark.parametrize("reply,code", [(550, "rejected"), (350, "uncertain")])
def test_final_data_reply(drafts, client, reply, code):
    mock, _ = client
    mock.data.return_value = (reply, b"private")
    with pytest.raises(DraftError, match=code):
        SMTPTransport().send(approve(drafts, create(drafts)), "synthetic", lambda: None)
