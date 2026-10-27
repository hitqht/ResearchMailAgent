"""Bounded MIME extraction; HTML never reaches an HTML renderer or network client."""

import hashlib
from datetime import UTC
from email import policy
from email.errors import MessageError
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

from researchmail.mail.models import Attachment, ParsedMessage

MAX_MESSAGE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_PARTS = 500


def header(value: str | None, limit: int = 2000) -> str:
    result: list[str] = []
    try:
        chunks = decode_header(value or "")
    except (ValueError, UnicodeError):
        chunks = [(value or "", None)]
    for chunk, charset in chunks:
        if isinstance(chunk, bytes):
            try:
                result.append(chunk.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                result.append(chunk.decode("utf-8", errors="replace"))
        else:
            result.append(chunk)
    return " ".join("".join(result).split())[:limit]


class SafeText(HTMLParser):
    BLOCKED = {"script", "style", "iframe", "object", "svg", "head", "template"}
    BREAKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCKED:
            self.hidden.append(tag)
        if not self.hidden and tag in self.BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.hidden:
            self.hidden = self.hidden[: self.hidden.index(tag)]
        if not self.hidden and tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = SafeText()
    parser.feed(value[: MAX_TEXT_CHARS * 4])
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())[
        :MAX_TEXT_CHARS
    ]


def _payload(part: Message) -> bytes:
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _text(part: Message) -> str:
    content = _payload(part)
    try:
        return content.decode(part.get_content_charset() or "utf-8", errors="replace")[
            :MAX_TEXT_CHARS
        ]
    except LookupError:
        return content.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]


def parse_message(raw: bytes) -> ParsedMessage:
    if len(raw) > MAX_MESSAGE_BYTES:
        return ParsedMessage(body="邮件超过 20 MiB，未缓存正文。", parse_status="oversized")
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        plain: list[str] = []
        html: list[str] = []
        attachments: list[Attachment] = []
        malformed = bool(message.defects)
        for count, part in enumerate(message.walk()):
            if count >= MAX_PARTS:
                malformed = True
                break
            if part.is_multipart():
                continue
            filename = part.get_filename()
            if filename is not None or part.get_content_disposition() == "attachment":
                attachments.append(
                    Attachment(
                        name=header(filename, 500) or "未命名附件",
                        content_type=part.get_content_type(),
                        size=len(_payload(part)),
                    )
                )
            elif part.get_content_type() == "text/plain":
                plain.append(_text(part))
            elif part.get_content_type() == "text/html":
                html.append(html_to_text(_text(part)))
            malformed = malformed or bool(part.defects)
        received_at = None
        try:
            date = parsedate_to_datetime(str(message.get("Date", "")))
            if date.tzinfo is not None:
                received_at = date.astimezone(UTC).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
        recipients = tuple(
            header(address)
            for _, address in getaddresses([str(message.get("To", "")), str(message.get("Cc", ""))])
            if address
        )
        return ParsedMessage(
            subject=header(str(message.get("Subject", ""))),
            sender=header(str(message.get("From", ""))),
            recipients=recipients,
            message_id=header(str(message.get("Message-ID", ""))) or None,
            received_at=received_at,
            body="\n\n".join(plain or html)[:MAX_TEXT_CHARS],
            attachments=tuple(attachments),
            parse_status="malformed" if malformed else "ok",
        )
    except (ValueError, TypeError, UnicodeError, RecursionError, LookupError, MessageError):
        return ParsedMessage(body="邮件 MIME 格式异常，无法安全解析。", parse_status="malformed")


def content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
