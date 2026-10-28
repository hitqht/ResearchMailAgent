"""TLS SMTP without retries. All RCPTs must be accepted before DATA is attempted."""

import smtplib
import ssl
from collections.abc import Callable
from contextlib import suppress
from email.message import EmailMessage
from email.policy import SMTP

from researchmail.drafts.models import DraftError, SendPreview
from researchmail.mail.models import Account


def wire_message(preview: SendPreview) -> bytes:
    preview.validate()
    message = EmailMessage(policy=SMTP)
    message["From"] = preview.account.config.email
    message["To"] = ", ".join(preview.draft.content.recipients)
    message["Subject"] = preview.draft.content.subject
    message["Message-ID"] = preview.draft.wire_message_id
    message["Date"] = preview.draft.wire_date
    message.set_content(preview.draft.content.body, charset="utf-8", cte="quoted-printable")
    return message.as_bytes()


class SMTPTransport:
    def send(self, preview: SendPreview, secret: str, before_data: Callable[[], None]) -> None:
        payload = wire_message(preview)
        client: smtplib.SMTP_SSL | None = None
        started = False
        try:
            config = preview.account.config
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=20,
                context=ssl.create_default_context(),
                local_hostname="researchmail.local",
            )
            client.set_debuglevel(0)
            client.ehlo_or_helo_if_needed()
            client.login(config.email, secret)
            code, _ = client.mail(config.email)
            if code != 250:
                raise DraftError("rejected")
            for recipient in preview.draft.content.recipients:
                code, _ = client.rcpt(recipient)
                if code not in {250, 251}:
                    with suppress(OSError):
                        client.rset()
                    raise DraftError("recipient")
            before_data()
            started = True
            code, _ = client.data(payload)
            if code != 250:
                raise DraftError("rejected" if 400 <= code <= 599 else "uncertain")
        except smtplib.SMTPAuthenticationError:
            raise DraftError("auth") from None
        except smtplib.SMTPDataError:
            # Explicit negative DATA reply before body transfer.
            raise DraftError("rejected") from None
        except OSError:
            raise DraftError("uncertain" if started else "network") from None
        finally:
            if client is not None:
                with suppress(OSError):
                    client.quit()
                with suppress(OSError):
                    client.close()

    def test_connection(self, account: Account, secret: str) -> None:
        client: smtplib.SMTP_SSL | None = None
        try:
            config = account.config
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=20,
                context=ssl.create_default_context(),
                local_hostname="researchmail.local",
            )
            client.set_debuglevel(0)
            client.ehlo_or_helo_if_needed()
            client.login(config.email, secret)
        except smtplib.SMTPAuthenticationError:
            raise DraftError("auth") from None
        except OSError:
            raise DraftError("network") from None
        finally:
            if client is not None:
                with suppress(OSError):
                    client.quit()
                with suppress(OSError):
                    client.close()
