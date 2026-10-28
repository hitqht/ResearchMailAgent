import json
import sqlite3
from datetime import UTC, datetime
from email.utils import format_datetime, make_msgid
from typing import cast

from researchmail.drafts.models import Draft, DraftContent, DraftError, DraftStatus, SendPreview
from researchmail.mail.models import Account, AccountConfig
from researchmail.storage.database import Database


class DraftRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _audit(
        conn: sqlite3.Connection, event: str, draft_id: int, outcome: str = "success"
    ) -> None:
        conn.execute(
            "INSERT INTO audit_events(event,entity_type,entity_id,outcome) VALUES (?,'draft',?,?)",
            (event, draft_id, outcome),
        )

    @staticmethod
    def _draft(row: sqlite3.Row) -> Draft:
        return Draft(
            row["id"],
            DraftContent(
                account_id=row["account_id"],
                message_id=row["message_id"],
                recipients=tuple(json.loads(row["recipients_json"])),
                subject=row["subject"],
                body=row["body_text"],
            ),
            row["revision"],
            DraftStatus(row["status"]),
            row["reviewed_digest"],
            row["approved_digest"],
            row["wire_message_id"] or "",
            row["wire_date"] or "",
            row["last_error"],
        )

    def _get(self, conn: sqlite3.Connection, draft_id: int) -> Draft:
        row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise DraftError("missing")
        return self._draft(row)

    def get(self, draft_id: int) -> Draft:
        with self.database.connection() as conn:
            return self._get(conn, draft_id)

    def list(self) -> list[Draft]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM drafts ORDER BY id DESC LIMIT 200").fetchall()
        return [self._draft(r) for r in rows]

    def create(self, content: DraftContent) -> int:
        with self.database.transaction() as conn:
            if content.message_id is not None:
                row = conn.execute(
                    "SELECT account_id FROM messages WHERE id=?", (content.message_id,)
                ).fetchone()
                if row is None:
                    raise DraftError("missing")
                if content.account_id is None:
                    content = content.model_copy(update={"account_id": row[0]})
            cur = conn.execute(
                "INSERT INTO drafts(account_id,message_id,recipients_json,subject,body_text,"
                "wire_message_id,wire_date) VALUES (?,?,?,?,?,?,?)",
                (
                    content.account_id,
                    content.message_id,
                    json.dumps(content.recipients),
                    content.subject,
                    content.body,
                    make_msgid(domain="researchmail.local"),
                    format_datetime(datetime.now(UTC)),
                ),
            )
            draft_id = cast(int, cur.lastrowid)
            self._audit(conn, "draft_created", draft_id)
        return draft_id

    def save(self, draft_id: int, content: DraftContent, revision: int) -> None:
        with self.database.transaction() as conn:
            draft = self._get(conn, draft_id)
            if draft.revision != revision:
                raise DraftError("stale")
            if draft.status in {DraftStatus.SENDING, DraftStatus.SENT, DraftStatus.UNCERTAIN}:
                raise DraftError("state")
            if content.message_id != draft.content.message_id:
                raise DraftError("config")
            conn.execute(
                "UPDATE drafts SET account_id=?,recipients_json=?,subject=?,body_text=? WHERE id=?",
                (
                    content.account_id,
                    json.dumps(content.recipients),
                    content.subject,
                    content.body,
                    draft_id,
                ),
            )

    def _preview(self, conn: sqlite3.Connection, draft_id: int) -> SendPreview:
        draft = self._get(conn, draft_id)
        if not draft.wire_message_id:
            conn.execute(
                "UPDATE drafts SET wire_message_id=?,wire_date=? WHERE id=?",
                (
                    make_msgid(domain="researchmail.local"),
                    format_datetime(datetime.now(UTC)),
                    draft_id,
                ),
            )
            draft = self._get(conn, draft_id)
        row = conn.execute(
            "SELECT * FROM accounts WHERE id=?", (draft.content.account_id,)
        ).fetchone()
        if row is None:
            raise DraftError("missing")
        account = Account(
            row["id"],
            AccountConfig(**{k: row[k] for k in AccountConfig.model_fields}),
            row["credential_ref"],
        )
        preview = SendPreview(draft, account)
        preview.validate()
        return preview

    def preview(self, draft_id: int) -> SendPreview:
        with self.database.transaction() as conn:
            return self._preview(conn, draft_id)

    def transition(self, draft_id: int, digest: str, action: str) -> None:
        with self.database.transaction() as conn:
            preview = self._preview(conn, draft_id)
            draft = preview.draft
            if preview.digest != digest:
                raise DraftError("stale")
            if action == "review":
                if draft.status not in {DraftStatus.DRAFT, DraftStatus.REVIEWED}:
                    raise DraftError("state")
                conn.execute(
                    "UPDATE drafts SET status='REVIEWED',reviewed_digest=?,approved_digest=NULL "
                    "WHERE id=?",
                    (digest, draft_id),
                )
            elif action == "approve":
                if draft.status != DraftStatus.REVIEWED:
                    raise DraftError("state")
                if draft.reviewed_digest != digest:
                    raise DraftError("stale")
                conn.execute(
                    "UPDATE drafts SET status='APPROVED',approved_digest=? WHERE id=?",
                    (digest, draft_id),
                )
            else:
                raise DraftError("config")
            self._audit(conn, "draft_" + action, draft_id)

    def reset_failed(self, draft_id: int) -> None:
        with self.database.transaction() as conn:
            if self._get(conn, draft_id).status != DraftStatus.FAILED:
                raise DraftError("state")
            conn.execute(
                "UPDATE drafts SET status='DRAFT',revision=revision+1,reviewed_digest=NULL,"
                "approved_digest=NULL,last_error=NULL WHERE id=?",
                (draft_id,),
            )
            self._audit(conn, "draft_reopened", draft_id)

    def claim(self, draft_id: int, digest: str, attempt_id: str) -> SendPreview:
        with self.database.transaction() as conn:
            preview = self._preview(conn, draft_id)
            draft = preview.draft
            if draft.status != DraftStatus.APPROVED:
                raise DraftError("state")
            if (
                preview.digest != digest
                or draft.approved_digest != digest
                or draft.reviewed_digest != digest
            ):
                raise DraftError("stale")
            conn.execute(
                "UPDATE drafts SET status='SENDING',last_error=NULL WHERE id=?", (draft_id,)
            )
            conn.execute(
                "INSERT INTO send_attempts(id,draft_id,revision,digest,envelope_json) "
                "VALUES (?,?,?,?,?)",
                (
                    attempt_id,
                    draft_id,
                    draft.revision,
                    digest,
                    json.dumps(
                        {
                            "from": preview.account.config.email,
                            "to": draft.content.recipients,
                            "smtp_host": preview.account.config.smtp_host,
                            "smtp_port": preview.account.config.smtp_port,
                            "message_id": draft.wire_message_id,
                            "date": draft.wire_date,
                        }
                    ),
                ),
            )
            self._audit(conn, "send_started", draft_id)
        return preview

    def data_started(self, attempt_id: str) -> None:
        with self.database.transaction() as conn:
            cur = conn.execute(
                "UPDATE send_attempts SET data_started=1 WHERE id=? AND outcome='pending'",
                (attempt_id,),
            )
            if cur.rowcount != 1:
                raise DraftError("state")

    def finish(self, attempt_id: str, status: DraftStatus, error: str | None = None) -> None:
        outcomes = {
            DraftStatus.SENT: "sent",
            DraftStatus.FAILED: "failed",
            DraftStatus.UNCERTAIN: "uncertain",
        }
        if status not in outcomes:
            raise DraftError("state")
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT draft_id FROM send_attempts WHERE id=? AND outcome='pending'", (attempt_id,)
            ).fetchone()
            if row is None:
                raise DraftError("state")
            conn.execute(
                "UPDATE send_attempts SET outcome=?,error_code=?,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (outcomes[status], error, attempt_id),
            )
            conn.execute(
                "UPDATE drafts SET status=?,last_error=?,approved_digest=NULL WHERE id=? "
                "AND status='SENDING'",
                (status, error, row[0]),
            )
            self._audit(
                conn,
                "send_" + outcomes[status],
                row[0],
                "success"
                if status == DraftStatus.SENT
                else "uncertain"
                if status == DraftStatus.UNCERTAIN
                else "error",
            )

    def recover(self) -> int:
        # Caller holds the process-wide outbox file lock; active sends cannot be recovered.
        with self.database.transaction() as conn:
            rows = conn.execute("SELECT id FROM drafts WHERE status='SENDING'").fetchall()
            for row in rows:
                self._audit(conn, "send_interrupted", row[0], "uncertain")
            conn.execute(
                "UPDATE drafts SET status='UNCERTAIN',last_error='uncertain',approved_digest=NULL "
                "WHERE status='SENDING'"
            )
            conn.execute(
                "UPDATE send_attempts SET outcome='uncertain',error_code='uncertain' "
                "WHERE outcome='pending'"
            )
        return len(rows)
