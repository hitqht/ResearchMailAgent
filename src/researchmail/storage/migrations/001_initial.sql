CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    imap_host TEXT NOT NULL DEFAULT 'imap.163.com',
    imap_port INTEGER NOT NULL DEFAULT 993 CHECK(imap_port BETWEEN 1 AND 65535),
    smtp_host TEXT NOT NULL DEFAULT 'smtp.163.com',
    smtp_port INTEGER NOT NULL DEFAULT 465 CHECK(smtp_port BETWEEN 1 AND 65535),
    status TEXT NOT NULL DEFAULT 'disabled' CHECK(status IN ('disabled','ready','error')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE sync_cursors (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    folder TEXT NOT NULL,
    uidvalidity INTEGER NOT NULL CHECK(uidvalidity > 0),
    last_uid INTEGER NOT NULL DEFAULT 0 CHECK(last_uid >= 0),
    status TEXT NOT NULL DEFAULT 'idle' CHECK(status IN ('idle','syncing','error')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(account_id,folder)
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    folder TEXT NOT NULL,
    uidvalidity INTEGER NOT NULL CHECK(uidvalidity > 0),
    uid INTEGER NOT NULL CHECK(uid > 0),
    message_id TEXT,
    subject TEXT NOT NULL DEFAULT '',
    sender TEXT NOT NULL DEFAULT '',
    recipients_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(recipients_json)),
    received_at TEXT,
    body_text TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(attachments_json)),
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','analyzed','error')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(account_id,folder,uidvalidity,uid)
);
CREATE INDEX idx_messages_received ON messages(account_id,received_at DESC);
CREATE TABLE analyses (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    skill_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    category TEXT CHECK(category IN ('submission','revision','review_invitation',
      'review_assignment','collaboration','institutional_notice','other')),
    confidentiality TEXT NOT NULL DEFAULT 'unknown'
      CHECK(confidentiality IN ('unknown','sensitive','public')),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    confidence REAL CHECK(confidence BETWEEN 0 AND 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','validated','rejected')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_analyses_message ON analyses(message_id);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    deadline TEXT,
    deadline_kind TEXT CHECK(deadline_kind IN
      ('invitation_response','review_report','revision','proof','other')),
    evidence TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'suggested' CHECK(status IN ('suggested','confirmed','done','dismissed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_tasks_deadline ON tasks(status,deadline);
CREATE TABLE drafts (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    recipients_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(recipients_json)),
    subject TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    approved_digest TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN
      ('DRAFT','REVIEWED','APPROVED','SENDING','SENT','UNCERTAIN','FAILED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    event TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    outcome TEXT NOT NULL CHECK(outcome IN ('success','denied','error','uncertain')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_audit_created ON audit_events(created_at);
