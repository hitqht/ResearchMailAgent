"""Typed persistence boundary. Credentials never pass through this module."""

import json
from typing import cast

from researchmail.mail.models import (
    Account,
    AccountConfig,
    Attachment,
    Folder,
    MessageView,
    ParsedMessage,
)
from researchmail.storage.database import Database


class MailRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def accounts(self) -> list[Account]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [
            Account(
                row["id"],
                AccountConfig(**{name: row[name] for name in AccountConfig.model_fields}),
                row["credential_ref"],
            )
            for row in rows
        ]

    def account(self, account_id: int) -> Account:
        return next(account for account in self.accounts() if account.id == account_id)

    def has_sync_state(self, account_id: int) -> bool:
        with self.database.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM sync_cursors WHERE account_id=? LIMIT 1", (account_id,)
                ).fetchone()
                is not None
            )

    def save_account(self, config: AccountConfig, reference: str, account_id: int | None) -> int:
        values = (
            config.email,
            config.display_name,
            config.imap_host,
            config.imap_port,
            config.smtp_host,
            config.smtp_port,
            config.sync_minutes,
            reference,
        )
        with self.database.transaction() as conn:
            if account_id is None:
                cursor = conn.execute(
                    "INSERT INTO accounts(email,display_name,imap_host,imap_port,smtp_host,"
                    "smtp_port,sync_minutes,credential_ref,status) "
                    "VALUES (?,?,?,?,?,?,?,?,'ready')",
                    values,
                )
                account_id = cast(int, cursor.lastrowid)
            else:
                cursor = conn.execute(
                    "UPDATE accounts SET email=?,display_name=?,imap_host=?,imap_port=?,"
                    "smtp_host=?,"
                    "smtp_port=?,sync_minutes=?,credential_ref=?,status='ready',"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (*values, account_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Unknown local account")
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) VALUES (?,?,?,?)",
                ("account_saved", "account", account_id, "success"),
            )
        return account_id

    def save_folders(self, account_id: int, folders: list[Folder]) -> None:
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM mail_folders WHERE account_id=?", (account_id,))
            conn.executemany(
                "INSERT INTO mail_folders(account_id,wire_name,display_name,selectable) "
                "VALUES (?,?,?,?)",
                [(account_id, f.wire_name, f.display_name, int(f.selectable)) for f in folders],
            )

    def folders(self, account_id: int) -> list[Folder]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mail_folders WHERE account_id=? ORDER BY wire_name", (account_id,)
            ).fetchall()
        return [
            Folder(row["wire_name"], row["display_name"], bool(row["selectable"])) for row in rows
        ]

    def start_cursor(self, account_id: int, folder: str, validity: int) -> tuple[int, bool]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM sync_cursors WHERE account_id=? AND folder=?", (account_id, folder)
            ).fetchone()
            changed = row is not None and row["uidvalidity"] != validity
            after = row["last_uid"] if row is not None and not changed else 0
            conn.execute(
                "INSERT INTO sync_cursors(account_id,folder,uidvalidity,last_uid,status) "
                "VALUES (?,?,?,?,'syncing') ON CONFLICT(account_id,folder) DO UPDATE SET "
                "uidvalidity=excluded.uidvalidity,last_uid=excluded.last_uid,status='syncing',"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (account_id, folder, validity, after),
            )
        return int(after), changed

    def store_message(
        self,
        account_id: int,
        folder: str,
        validity: int,
        uid: int,
        parsed: ParsedMessage | None,
        size: int,
        digest: str | None,
    ) -> bool:
        with self.database.transaction() as conn:
            inserted = False
            if parsed is not None:
                cursor = conn.execute(
                    "INSERT INTO messages(account_id,folder,uidvalidity,uid,subject,sender,"
                    "recipients_json,message_id,received_at,body_text,attachments_json,content_hash,"
                    "size_bytes,parse_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(account_id,folder,uidvalidity,uid) DO NOTHING",
                    (
                        account_id,
                        folder,
                        validity,
                        uid,
                        parsed.subject,
                        parsed.sender,
                        json.dumps(parsed.recipients, ensure_ascii=False),
                        parsed.message_id,
                        parsed.received_at,
                        parsed.body,
                        json.dumps(
                            [a.model_dump() for a in parsed.attachments], ensure_ascii=False
                        ),
                        digest,
                        size,
                        parsed.parse_status,
                    ),
                )
                inserted = cursor.rowcount == 1
            cursor = conn.execute(
                "UPDATE sync_cursors SET last_uid=max(last_uid,?),"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE account_id=? AND folder=? AND uidvalidity=?",
                (uid, account_id, folder, validity),
            )
            if cursor.rowcount != 1:
                raise ValueError("Cursor generation changed")
        return inserted

    def finish_cursor(self, account_id: int, folder: str, error: bool = False) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE sync_cursors SET status=? WHERE account_id=? AND folder=?",
                ("error" if error else "idle", account_id, folder),
            )
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) VALUES (?,?,?,?)",
                ("mail_sync", "account", account_id, "error" if error else "success"),
            )

    def messages(
        self, account_id: int, folder: str, search: str = "", offset: int = 0, limit: int = 100
    ) -> list[MessageView]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT m.* FROM messages m JOIN sync_cursors c ON "
                "c.account_id=m.account_id AND c.folder=m.folder AND c.uidvalidity=m.uidvalidity "
                "WHERE m.account_id=? AND m.folder=? AND "
                "(?='' OR instr(lower(m.subject),lower(?))>0 OR instr(lower(m.sender),lower(?))>0) "
                "ORDER BY m.uid DESC LIMIT ? OFFSET ?",
                (
                    account_id,
                    folder,
                    search,
                    search,
                    search,
                    min(max(limit, 1), 100),
                    max(offset, 0),
                ),
            ).fetchall()
        return [
            MessageView(
                row["id"],
                row["account_id"],
                row["folder"],
                row["uidvalidity"],
                row["uid"],
                ParsedMessage(
                    subject=row["subject"],
                    sender=row["sender"],
                    recipients=tuple(json.loads(row["recipients_json"])),
                    message_id=row["message_id"],
                    received_at=row["received_at"],
                    body=row["body_text"],
                    attachments=tuple(
                        Attachment.model_validate(a) for a in json.loads(row["attachments_json"])
                    ),
                    parse_status=row["parse_status"],
                ),
                row["size_bytes"],
            )
            for row in rows
        ]
