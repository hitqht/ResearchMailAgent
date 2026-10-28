import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from researchmail.drafts.models import DraftContent, DraftError, DraftStatus
from researchmail.llm.models import AIError
from researchmail.services.draft_service import DraftService
from researchmail.storage.database import Database, StorageError, packaged_migrations
from researchmail.tools.registry import Origin, ToolRegistry


class RecordingTransport:
    def __init__(self):
        self.sent = []
        self.error = None
        self.after_data = True

    def send(self, preview, secret, before_data):
        if not self.after_data and self.error:
            raise self.error
        before_data()
        self.sent.append((preview, secret))
        if self.error:
            raise self.error


def create(engine):
    return engine.repository.create(
        DraftContent(
            account_id=1,
            recipients=("editor@example.invalid",),
            subject="Synthetic submission",
            body="Synthetic draft.\nNo real mail.",
        )
    )


def approve(engine, draft_id):
    preview = engine.repository.preview(draft_id)
    engine.repository.transition(draft_id, preview.digest, "review")
    engine.repository.transition(draft_id, preview.digest, "approve")
    return engine.repository.preview(draft_id)


def test_full_state_flow_and_no_repeat(drafts):
    draft = create(drafts)
    with pytest.raises(DraftError, match="state"):
        drafts.authorize_send(drafts.repository.preview(draft))
    with pytest.raises(DraftError, match="state"):
        drafts.repository.transition(draft, drafts.repository.preview(draft).digest, "approve")
    preview = approve(drafts, draft)
    token = drafts.authorize_send(preview)
    assert drafts.send_approved(draft, token) == DraftStatus.SENT
    assert len(drafts.transport.sent) == 1
    with pytest.raises(DraftError, match="denied"):
        drafts.send_approved(draft, token)
    with pytest.raises(DraftError, match="state"):
        drafts.authorize_send(preview)
    assert drafts.repository.get(draft).status == DraftStatus.SENT


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", "Changed"),
        ("body", "Changed body"),
        ("recipients", ("other@example.invalid",)),
        ("account_id", 2),
    ],
)
def test_edit_invalidates_review_approval_and_send_token(drafts, service, field, value):
    with service.database.transaction() as conn:
        conn.execute(
            "INSERT INTO accounts(id,email,credential_ref) VALUES (2,?,?)",
            ("other@example.invalid", "unused-other"),
        )
    draft = create(drafts)
    preview = approve(drafts, draft)
    token = drafts.authorize_send(preview)
    changed = preview.draft.content.model_copy(update={field: value})
    drafts.repository.save(draft, changed, preview.draft.revision)
    current = drafts.repository.get(draft)
    assert current.status == DraftStatus.DRAFT and current.revision == preview.draft.revision + 1
    assert current.approved_digest is None and current.reviewed_digest is None
    with pytest.raises(DraftError):
        drafts.send_approved(draft, token)
    assert not drafts.transport.sent


@pytest.mark.parametrize(
    "column,value",
    [
        ("smtp_host", "smtp.other.invalid"),
        ("smtp_port", 466),
        ("email", "changed@example.invalid"),
        ("credential_ref", "rotated"),
    ],
)
def test_account_changes_cannot_reuse_approval(drafts, service, column, value):
    draft = create(drafts)
    preview = approve(drafts, draft)
    token = drafts.authorize_send(preview)
    allowed = {"smtp_host", "smtp_port", "email", "credential_ref"}
    assert column in allowed
    with service.database.transaction() as conn:
        conn.execute(f"UPDATE accounts SET {column}=? WHERE id=1", (value,))
    assert drafts.repository.get(draft).status == DraftStatus.DRAFT
    with pytest.raises(DraftError, match="state"):
        drafts.send_approved(draft, token)
    assert not drafts.transport.sent


def test_atomic_claim_concurrent_services(drafts, service):
    draft = create(drafts)
    preview = approve(drafts, draft)
    other = DraftService(service.database, drafts.vault, drafts.transport)
    tokens = [drafts.authorize_send(preview), other.authorize_send(preview)]
    barrier = threading.Barrier(2)

    def send(i):
        barrier.wait()
        try:
            return [drafts, other][i].send_approved(draft, tokens[i])
        except DraftError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(send, range(2)))
    assert DraftStatus.SENT in results and len(drafts.transport.sent) == 1


@pytest.mark.parametrize(
    "after,status", [(False, DraftStatus.FAILED), (True, DraftStatus.UNCERTAIN)]
)
def test_timeout_boundaries_no_auto_retry(drafts, after, status):
    draft = create(drafts)
    preview = approve(drafts, draft)
    drafts.transport.error = TimeoutError("private provider response")
    drafts.transport.after_data = after
    with pytest.raises(DraftError) as error:
        drafts.send_approved(draft, drafts.authorize_send(preview))
    assert "private" not in str(error.value)
    assert drafts.repository.get(draft).status == status
    if status == DraftStatus.FAILED:
        drafts.repository.reset_failed(draft)
        assert drafts.repository.get(draft).status == DraftStatus.DRAFT
        with pytest.raises(DraftError):
            drafts.authorize_send(drafts.repository.preview(draft))
    else:
        with pytest.raises(DraftError):
            drafts.repository.reset_failed(draft)
        with pytest.raises(DraftError):
            drafts.repository.save(draft, preview.draft.content, preview.draft.revision)


def test_post_acceptance_storage_failure_stays_uncertain(drafts, monkeypatch):
    draft = create(drafts)
    preview = approve(drafts, draft)
    original = drafts.repository.finish

    def fail(*args):
        raise StorageError("synthetic disk failure")

    monkeypatch.setattr(drafts.repository, "finish", fail)
    with pytest.raises(DraftError, match="uncertain"):
        drafts.send_approved(draft, drafts.authorize_send(preview))
    assert len(drafts.transport.sent) == 1
    monkeypatch.setattr(drafts.repository, "finish", original)
    assert drafts.recover_interrupted() == 1
    assert drafts.repository.get(draft).status == DraftStatus.UNCERTAIN
    with pytest.raises(DraftError):
        drafts.authorize_send(preview)


def test_interrupted_send_recovery_excludes_active_process(drafts, service):
    draft = create(drafts)
    preview = approve(drafts, draft)
    with drafts._outbox_lock():
        drafts.repository.claim(draft, preview.digest, "synthetic-attempt")
        assert DraftService(service.database).recover_interrupted() == 0
        assert drafts.repository.get(draft).status == DraftStatus.SENDING
    assert drafts.recover_interrupted() == 1
    assert drafts.repository.get(draft).status == DraftStatus.UNCERTAIN


def test_tokens_expire_cannot_cross_drafts_or_bypass_policy(drafts, monkeypatch, service):
    draft = create(drafts)
    preview = approve(drafts, draft)
    token = drafts.authorize_send(preview)
    registry = ToolRegistry(service.database, drafts)
    with pytest.raises(AIError, match="denied"):
        registry.call(
            "mail.send_approved",
            {"draft_id": draft, "confirmation_token": token},
            origin=Origin.MODEL,
        )
    monkeypatch.setattr("researchmail.services.draft_service.time.monotonic", lambda: float("inf"))
    with pytest.raises(DraftError, match="denied"):
        drafts.send_approved(draft, token)
    assert not drafts.transport.sent


def test_user_registry_send_requires_same_host_confirmation(drafts, service):
    draft = create(drafts)
    preview = approve(drafts, draft)
    result = ToolRegistry(service.database, drafts).call(
        "mail.send_approved",
        {"draft_id": draft, "confirmation_token": drafts.authorize_send(preview)},
        origin=Origin.USER,
    )
    assert result == DraftStatus.SENT


@pytest.mark.parametrize(
    "bad",
    [
        {"subject": "Subject\r\nBcc: injected@example.invalid"},
        {"recipients": ("display name <test@example.invalid>",)},
        {"recipients": ("test@example.invalid\nRCPT TO: other@example.invalid",)},
        {"recipients": ("same@example.invalid", "same@example.invalid")},
        {"recipients": ("姓名@example.invalid",)},
        {"body": "bad\x00body"},
    ],
)
def test_header_and_envelope_injection_rejected(bad):
    with pytest.raises(ValidationError):
        DraftContent.model_validate(
            {"recipients": ("safe@example.invalid",), "subject": "Test", "body": "Test", **bad}
        )


def test_model_generation_local_only_and_never_sends(drafts, ai):
    ai[1].response = json.dumps({"subject": "Re: Revision", "body": "请提供修改要求以便确认。"})
    draft = drafts.create_reply(1, "请澄清修改要求", ai[3], True)
    assert drafts.repository.get(draft).status == DraftStatus.DRAFT
    assert not drafts.transport.sent
    with pytest.raises(AIError, match="privacy"):
        drafts.create_reply(1, "回复", ai[4], True)
    ai[1].response = json.dumps(
        {"subject": "Re: Test", "body": "x", "recipients": ["evil@example.invalid"]}
    )
    with pytest.raises(AIError, match="response"):
        drafts.create_reply(1, "回复", ai[3], True)


def test_database_trigger_cannot_leave_changed_content_approved(drafts, service):
    draft = create(drafts)
    preview = approve(drafts, draft)
    with service.database.transaction() as conn:
        conn.execute("UPDATE drafts SET body_text=? WHERE id=?", ("Changed", draft))
    assert drafts.repository.get(draft).status == DraftStatus.DRAFT
    assert drafts.repository.get(draft).approved_digest is None
    with pytest.raises(DraftError, match="stale"):
        drafts.repository.transition(draft, preview.digest, "review")


def test_m2_migration_keeps_legacy_draft(paths):
    db = Database(paths.database)
    db.initialize(packaged_migrations()[:4])
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO accounts(id,email,credential_ref) VALUES (1,?,?)",
            ("old@example.invalid", "unused"),
        )
        conn.execute(
            "INSERT INTO drafts(account_id,recipients_json,subject,body_text,status,"
            "approved_digest) "
            "VALUES (1,?,'Old','Body','APPROVED','legacy')",
            ('["to@example.invalid"]',),
        )
    assert db.initialize() == len(packaged_migrations())
    engine = DraftService(db)
    preview = engine.repository.preview(1)
    assert preview.draft.content.subject == "Old" and preview.draft.status == DraftStatus.DRAFT
    assert preview.draft.wire_message_id and preview.draft.approved_digest is None


def test_sent_content_is_immutable_and_envelope_snapshot_preserved(drafts, service):
    draft = create(drafts)
    preview = approve(drafts, draft)
    drafts.send_approved(draft, drafts.authorize_send(preview))
    with pytest.raises(StorageError), service.database.transaction() as conn:
        conn.execute("UPDATE drafts SET body_text=? WHERE id=?", ("Changed", draft))
    with service.database.transaction() as conn:
        conn.execute("UPDATE accounts SET smtp_host=? WHERE id=1", ("new.invalid",))
    with service.database.connection() as conn:
        snapshot = json.loads(
            conn.execute(
                "SELECT envelope_json FROM send_attempts WHERE draft_id=?", (draft,)
            ).fetchone()[0]
        )
        audit = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM audit_events"))
    assert snapshot["smtp_host"] == "smtp.163.com"
    assert "Synthetic draft" not in audit and "synthetic-smtp" not in audit


def test_local_reply_ignores_cloud_default(drafts, ai):
    from researchmail.llm.models import Preferences

    ai[0].repository.save_preferences(Preferences(default_model_id=ai[4], local_first=False))
    ai[1].response = json.dumps({"subject": "Re: Synthetic", "body": "请澄清。"})
    draft = drafts.create_reply(1, "请澄清", None, True)
    assert drafts.repository.get(draft).status == DraftStatus.DRAFT
