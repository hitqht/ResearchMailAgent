from datetime import date
from enum import StrEnum
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AIError(Exception):
    """Contains only an allowlisted code, never provider responses or credentials."""

    def __init__(self, code: str) -> None:
        self.code = code if code in ERRORS else "storage"
        super().__init__(self.code)


ERRORS = {
    "config": "模型配置无效，请检查名称、地址与认证方式。",
    "missing": "请先在设置中保存模型配置。",
    "local": "本地优先已开启，但尚未配置本地模型。请添加 Ollama 模型。",
    "privacy": "云端处理已阻止。需要你明确授权这封邮件及该模型，才能发送邮件内容。",
    "network": "无法连接模型。请检查 Ollama 是否运行、模型是否安装，或检查网络后重试。",
    "timeout": "模型请求超时。请稍后重试；未自动切换模型。",
    "auth": "模型认证失败，请更新 Keychain 中的 API Key。",
    "response": "模型返回格式无效，或证据、日期不符合原文。未保存本次分析。",
    "keychain": "无法访问模型钥匙串，请检查 macOS 钥匙串权限。",
    "storage": "无法完成本地操作，请检查数据库与磁盘空间。",
    "denied": "此工具调用未获授权。",
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelConfig(Contract):
    label: str = Field(min_length=1, max_length=80)
    provider: Literal["ollama", "openai_compatible"]
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(max_length=500)
    auth: Literal["none", "bearer", "x-api-key"] = "none"

    @field_validator("label", "model")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid model name")
        return value

    @model_validator(mode="after")
    def endpoint(self) -> "ModelConfig":
        parts = urlsplit(self.base_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or any(c.isspace() for c in self.base_url)
        ):
            raise ValueError("Invalid endpoint")
        try:
            _ = parts.port
        except ValueError:
            raise ValueError("Invalid port") from None
        if self.provider == "ollama":
            if "cloud" in self.model.casefold():
                raise ValueError("Cloud models are not local")
            if not self.local or parts.path not in {"", "/"} or self.auth != "none":
                raise ValueError("Ollama must use a loopback endpoint without authentication")
        elif parts.scheme != "https":
            raise ValueError("Cloud requires HTTPS")
        return self

    @property
    def local(self) -> bool:
        if self.provider != "ollama":
            return False
        host = urlsplit(self.base_url).hostname or ""
        # Numeric loopback only: no DNS rebinding or localhost proxy resolution.
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False


class SavedModel(Contract):
    id: int
    config: ModelConfig
    credential_ref: str | None


class Category(StrEnum):
    SUBMISSION = "submission"
    REVISION = "revision"
    INVITATION = "review_invitation"
    REVIEW = "review_assignment"
    COLLABORATION = "collaboration"
    NOTICE = "institutional_notice"
    OTHER = "other"


DeadlineKind = Literal["invitation_response", "review_report", "revision", "proof", "other"]


class TaskSuggestion(Contract):
    title: str = Field(min_length=1, max_length=300)
    deadline: date | None
    deadline_kind: DeadlineKind
    evidence: str = Field(min_length=1, max_length=2000)


class Analysis(Contract):
    category: Category
    priority: Literal["high", "normal", "low"]
    confidentiality: Literal["unknown", "sensitive", "public"]
    summary: str = Field(min_length=1, max_length=4000)
    evidence: tuple[str, ...] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    tasks: tuple[TaskSuggestion, ...] = Field(max_length=20)


class TaskRecord(Contract):
    id: int
    message_id: int | None
    title: str
    deadline: date | None
    deadline_kind: DeadlineKind | None
    evidence: str | None
    status: Literal["suggested", "confirmed", "done", "dismissed"]


class Preferences(Contract):
    default_model_id: int | None = None
    local_first: bool = True
    reminders: bool = False
    reminder_days: int = Field(default=3, ge=0, le=30)
