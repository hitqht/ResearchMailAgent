import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from researchmail.mail.models import Account

ERRORS = {
    "config": "请填写发件账户、有效的收件邮箱、主题和正文。收件人仅支持独立的 ASCII 邮箱地址。",
    "missing": "草稿或发件账户不存在，请刷新后重试。",
    "stale": "草稿或发件配置已变化，请重新保存、审核并批准当前版本。",
    "state": "当前状态不允许此操作。发送中、已发送及结果待核实的草稿不可再次发送或编辑。",
    "denied": "发送未获本次明确确认，或确认已过期。请从草稿界面重新核对。",
    "busy": "另一项发送正在进行，请等待操作结束。",
    "auth": "SMTP认证失败，请检查邮箱授权码与服务设置，再重新审核草稿。",
    "keychain": "无法读取发件账户的 Keychain 凭据。请在本机检查钥匙串权限。",
    "network": "连接SMTP失败，尚未提交正文。请检查网络并重新审核后再试。",
    "recipient": "至少一个收件地址被服务器拒绝，整封邮件未提交。请核对全部收件地址。",
    "rejected": "SMTP服务器明确拒绝本次提交。请检查账户、邮件内容或服务限制。",
    "uncertain": "发送结果待核实，请在163网页邮箱或向收件人核查。此草稿已禁止重发。",
    "storage": "本地保存失败，请检查数据库和磁盘空间；发送中的结果需要核实。",
}


class DraftError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if code in ERRORS else "storage"
        super().__init__(self.code)


class DraftStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    SENDING = "SENDING"
    SENT = "SENT"
    UNCERTAIN = "UNCERTAIN"
    FAILED = "FAILED"


def address(value: str) -> str:
    if len(value) > 254 or not re.fullmatch(
        r"[A-Za-z0-9_%+.-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
        value,
    ):
        raise ValueError("Invalid mailbox")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Invalid mailbox")
    return local + "@" + domain.lower()


class DraftContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account_id: int | None = Field(default=None, gt=0)
    message_id: int | None = Field(default=None, gt=0)
    recipients: tuple[str, ...] = Field(max_length=30)
    subject: str = Field(max_length=1000)
    body: str = Field(max_length=200000)

    @field_validator("recipients")
    @classmethod
    def mailboxes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        result = tuple(address(v.strip()) for v in values)
        if len({v.casefold() for v in result}) != len(result):
            raise ValueError("Duplicate recipients")
        return result

    @field_validator("subject")
    @classmethod
    def header(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid subject")
        return value

    @field_validator("body")
    @classmethod
    def text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Invalid body")
        return value


@dataclass(frozen=True)
class Draft:
    id: int
    content: DraftContent
    revision: int
    status: DraftStatus
    reviewed_digest: str | None
    approved_digest: str | None
    wire_message_id: str
    wire_date: str
    last_error: str | None


@dataclass(frozen=True)
class SendPreview:
    draft: Draft
    account: Account

    @property
    def digest(self) -> str:
        payload = {
            "draft": self.draft.content.model_dump(mode="json"),
            "revision": self.draft.revision,
            "wire_id": self.draft.wire_message_id,
            "wire_date": self.draft.wire_date,
            "from": self.account.config.email,
            "host": self.account.config.smtp_host,
            "port": self.account.config.smtp_port,
            "credential_ref": self.account.credential_ref,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate(self) -> None:
        try:
            address(self.account.config.email)
        except ValueError:
            raise DraftError("config") from None
        c = self.draft.content
        if (
            not c.recipients
            or not c.subject.strip()
            or not c.body.strip()
            or not self.account.credential_ref
        ):
            raise DraftError("config")
