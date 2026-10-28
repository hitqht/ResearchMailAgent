import pytest

from researchmail.llm.models import AIError
from researchmail.tools.registry import SCHEMAS, Origin, ToolRegistry


def test_schema_contracts_and_denied_model_mutations(ai, service):
    registry = ToolRegistry(service.database)
    assert {s["name"] for s in registry.schemas()} == set(SCHEMAS)
    assert "mail.send_approved" in SCHEMAS
    for name in (*SCHEMAS, "mail.send_approved", "shell.exec", "settings.update"):
        if name == "mail.get_message":
            continue
        with pytest.raises(AIError, match="denied"):
            registry.call(name, {}, origin=Origin.MODEL, message_scope=1)
    with pytest.raises(AIError, match="denied"):
        registry.call("mail.get_message", {"message_id": 2}, origin=Origin.MODEL, message_scope=1)
    with pytest.raises(AIError, match="config"):
        registry.call(
            "mail.get_message",
            {"message_id": 1, "origin": "user"},
            origin=Origin.MODEL,
            message_scope=1,
        )
    assert (
        registry.call("mail.get_message", {"message_id": 1}, origin=Origin.MODEL, message_scope=1)[
            "subject"
        ]
        == "Revision"
    )


def test_user_local_tools_no_send_path(ai, service):
    registry = ToolRegistry(service.database)
    params = dict(
        message_id=1, title="Test", deadline=None, deadline_kind="other", evidence="User input"
    )
    task = registry.call("tasks.create_local", params, origin=Origin.USER)
    assert task == registry.call("tasks.create_local", params, origin=Origin.USER)
    registry.call("tasks.update_local", dict(task_id=task, status="confirmed"), origin=Origin.USER)
    assert registry.call("tasks.list", {}, origin=Origin.USER)[0].status == "confirmed"
    assert len(registry.call("mail.list_messages", dict(account_id=1), origin=Origin.USER)) == 1
    assert registry.call(
        "mail.search_messages", dict(account_id=1, search="revision"), origin=Origin.USER
    )
    draft = registry.call(
        "drafts.create_local",
        dict(
            message_id=1,
            recipients=["test@example.invalid"],
            subject="Synthetic",
            body="Draft only",
        ),
        origin=Origin.USER,
    )
    with service.database.connection() as conn:
        assert (
            conn.execute("SELECT status FROM drafts WHERE id=?", (draft,)).fetchone()[0] == "DRAFT"
        )
    with pytest.raises(AIError, match="config"):
        registry.call("mail.send_approved", dict(draft_id=draft), origin=Origin.USER)
