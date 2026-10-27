from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Failure(StrEnum):
    AUTH = "auth"
    NETWORK = "network"
    PROTOCOL = "protocol"
    KEYCHAIN = "keychain"
    CONFIG = "config"
    STORAGE = "storage"
    BUSY = "busy"
    IDENTITY = "identity"
    DUPLICATE = "duplicate"


ERROR_TEXT = {
    Failure.AUTH: "认证失败。请在163网页邮箱开启 IMAP，并使用客户端授权码。",
    Failure.NETWORK: "连接中断或超时。请检查网络与服务器地址后重试，已同步数据会保留。",
    Failure.PROTOCOL: "服务器响应异常或不支持只读访问。请检查目录及 IMAP 设置。",
    Failure.KEYCHAIN: "无法访问 macOS 钥匙串。请解锁钥匙串并允许本应用访问后重试。",
    Failure.CONFIG: "配置不完整。请填写有效邮箱、服务器、端口和客户端授权码。",
    Failure.STORAGE: "本地保存未完成。请检查磁盘空间与文件权限后重试。",
    Failure.BUSY: "已有邮箱操作正在运行，请稍后重试。",
    Failure.IDENTITY: "该账户已有同步记录，暂不支持更换邮箱地址或收件服务器。请保留此账户。",
    Failure.DUPLICATE: "此邮箱已在本机配置，请选择已有账户编辑。",
}


class MailError(Exception):
    def __init__(self, code: Failure) -> None:
        self.code = code
        super().__init__(code.value)


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(default="", max_length=100)
    imap_host: str = "imap.163.com"
    imap_port: int = Field(default=993, ge=1, le=65535)
    smtp_host: str = "smtp.163.com"
    smtp_port: int = Field(default=465, ge=1, le=65535)
    sync_minutes: int = Field(default=0, ge=0, le=1440)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip()
        if value.count("@") != 1 or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Invalid account address")
        if not all(value.split("@")):
            raise ValueError("Invalid account address")
        return value

    @field_validator("imap_host", "smtp_host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or len(value) > 253
            or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:"
                for c in value
            )
        ):
            raise ValueError("Invalid server host")
        return value

    @field_validator("sync_minutes")
    @classmethod
    def valid_interval(cls, value: int) -> int:
        if value != 0 and value < 5:
            raise ValueError("Minimum interval is five minutes")
        return value


@dataclass(frozen=True)
class Account:
    id: int
    config: AccountConfig
    credential_ref: str | None


@dataclass(frozen=True)
class Folder:
    wire_name: str
    display_name: str
    selectable: bool = True


class Attachment(BaseModel):
    name: str
    content_type: str
    size: int


@dataclass(frozen=True)
class ParsedMessage:
    subject: str = ""
    sender: str = ""
    recipients: tuple[str, ...] = ()
    message_id: str | None = None
    received_at: str | None = None
    body: str = ""
    attachments: tuple[Attachment, ...] = ()
    parse_status: Literal["ok", "malformed", "oversized"] = "ok"


@dataclass(frozen=True)
class MessageView:
    id: int
    account_id: int
    folder: str
    uidvalidity: int
    uid: int
    parsed: ParsedMessage
    size_bytes: int


@dataclass(frozen=True)
class SyncResult:
    imported: int
    remaining: int
    cancelled: bool = False
    uidvalidity_changed: bool = False
