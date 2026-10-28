ALTER TABLE drafts ADD COLUMN reviewed_digest TEXT;
ALTER TABLE drafts ADD COLUMN wire_message_id TEXT;
ALTER TABLE drafts ADD COLUMN wire_date TEXT;
ALTER TABLE drafts ADD COLUMN last_error TEXT;
CREATE TABLE send_attempts (
    id TEXT PRIMARY KEY,
    draft_id INTEGER NOT NULL REFERENCES drafts(id),
    revision INTEGER NOT NULL,
    digest TEXT NOT NULL,
    envelope_json TEXT NOT NULL CHECK(json_valid(envelope_json)),
    data_started INTEGER NOT NULL DEFAULT 0 CHECK(data_started IN (0,1)),
    outcome TEXT NOT NULL DEFAULT 'pending' CHECK(outcome IN ('pending','sent','failed','uncertain')),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_attempts_draft ON send_attempts(draft_id);
CREATE TRIGGER protect_delivered_draft BEFORE UPDATE OF
 account_id,recipients_json,subject,body_text,wire_message_id,wire_date ON drafts
WHEN OLD.status IN ('SENDING','SENT','UNCERTAIN') AND (
 NEW.account_id IS NOT OLD.account_id OR NEW.recipients_json IS NOT OLD.recipients_json OR
 NEW.subject IS NOT OLD.subject OR NEW.body_text IS NOT OLD.body_text OR
 NEW.wire_message_id IS NOT OLD.wire_message_id OR NEW.wire_date IS NOT OLD.wire_date)
BEGIN
 SELECT RAISE(ABORT,'Delivery state is locked');
END;
CREATE TRIGGER invalidate_draft_approval AFTER UPDATE OF
 account_id,recipients_json,subject,body_text,wire_message_id,wire_date ON drafts
WHEN NEW.account_id IS NOT OLD.account_id OR NEW.recipients_json IS NOT OLD.recipients_json OR
 NEW.subject IS NOT OLD.subject OR NEW.body_text IS NOT OLD.body_text OR
 NEW.wire_message_id IS NOT OLD.wire_message_id OR NEW.wire_date IS NOT OLD.wire_date
BEGIN
 UPDATE drafts SET revision=OLD.revision+1,status='DRAFT',approved_digest=NULL,
 reviewed_digest=NULL,last_error=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
 INSERT INTO audit_events(event,entity_type,entity_id,outcome)
 VALUES('draft_edited','draft',NEW.id,'success');
END;
CREATE TRIGGER invalidate_account_approvals AFTER UPDATE OF email,smtp_host,smtp_port,credential_ref
ON accounts WHEN NEW.email IS NOT OLD.email OR NEW.smtp_host IS NOT OLD.smtp_host OR
 NEW.smtp_port IS NOT OLD.smtp_port OR NEW.credential_ref IS NOT OLD.credential_ref
BEGIN
 UPDATE drafts SET status='DRAFT',revision=revision+1,reviewed_digest=NULL,approved_digest=NULL,
 updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE account_id=NEW.id
 AND status IN ('REVIEWED','APPROVED');
 INSERT INTO audit_events(event,entity_type,entity_id,outcome)
 VALUES('account_approvals_invalidated','account',NEW.id,'success');
END;
