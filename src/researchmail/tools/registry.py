import json
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, ValidationError

from researchmail.drafts.models import DraftContent
from researchmail.llm.models import AIError, Contract, TaskSuggestion
from researchmail.services.draft_service import DraftService
from researchmail.storage.ai_repository import AIRepository
from researchmail.storage.database import Database
from researchmail.storage.mail_repository import MailRepository


class Origin(StrEnum):
    USER = "user"
    MODEL = "model"


class ListMail(Contract):
    account_id: int = Field(gt=0)
    folder: str = Field(default="INBOX", max_length=1000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class SearchMail(ListMail):
    search: str = Field(min_length=1, max_length=200)


class GetMail(Contract):
    message_id: int = Field(gt=0)


class Empty(Contract):
    pass


class CreateTask(TaskSuggestion):
    message_id: int | None = Field(default=None, gt=0)


class UpdateTask(Contract):
    task_id: int = Field(gt=0)
    status: Literal["suggested", "confirmed", "done", "dismissed"]
    deadline: date | None = None
    edit_deadline: bool = False


class CreateDraft(Contract):
    account_id: int | None = Field(default=None, gt=0)
    message_id: int | None = Field(default=None, gt=0)
    recipients: tuple[str, ...] = Field(max_length=30)
    subject: str = Field(max_length=1000)
    body: str = Field(max_length=200000)


class SendApproved(Contract):
    draft_id: int = Field(gt=0)
    confirmation_token: str = Field(min_length=20, max_length=200)


SCHEMAS: dict[str, type[Contract]] = {
    "mail.list_messages": ListMail,
    "mail.get_message": GetMail,
    "mail.search_messages": SearchMail,
    "tasks.list": Empty,
    "tasks.create_local": CreateTask,
    "tasks.update_local": UpdateTask,
    "drafts.create_local": CreateDraft,
    "mail.send_approved": SendApproved,
}


class ToolRegistry:
    def __init__(self, database: Database, draft_service: DraftService | None = None) -> None:
        self.database = database
        self.repository = AIRepository(database)
        self.mail = MailRepository(database)
        self.drafts = draft_service if draft_service is not None else DraftService(database)

    def schemas(self) -> list[dict[str, object]]:
        return [
            {"name": name, "inputSchema": schema.model_json_schema()}
            for name, schema in SCHEMAS.items()
        ]

    def call(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        origin: Origin,
        message_scope: int | None = None,
    ) -> object:
        # origin and scope come from trusted host code, never parsed from tool arguments.
        if name not in SCHEMAS or (
            origin != Origin.USER
            and not (
                origin == Origin.MODEL
                and name == "mail.get_message"
                and message_scope is not None
                and arguments.get("message_id") == message_scope
            )
        ):
            self.repository.audit("tool_denied", None, "denied")
            raise AIError("denied")
        try:
            args = SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            raise AIError("config") from None
        if isinstance(args, ListMail):
            return self.mail.messages(
                args.account_id,
                args.folder,
                args.search if isinstance(args, SearchMail) else "",
                args.offset,
                args.limit,
            )
        if isinstance(args, GetMail):
            return json.loads(self.repository.source(args.message_id))
        if isinstance(args, CreateTask):
            return self.repository.create_task(
                TaskSuggestion.model_validate(args.model_dump(exclude={"message_id"})),
                args.message_id,
            )
        if isinstance(args, UpdateTask):
            self.repository.update_task(
                args.task_id, args.status, args.deadline, args.edit_deadline
            )
            return True
        if isinstance(args, CreateDraft):
            return self.drafts.repository.create(DraftContent.model_validate(args.model_dump()))
        if isinstance(args, SendApproved):
            return self.drafts.send_approved(args.draft_id, args.confirmation_token)
        return self.repository.tasks()
