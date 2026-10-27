ALTER TABLE accounts ADD COLUMN credential_ref TEXT;
ALTER TABLE accounts ADD COLUMN sync_minutes INTEGER NOT NULL DEFAULT 0
  CHECK(sync_minutes = 0 OR sync_minutes BETWEEN 5 AND 1440);
CREATE UNIQUE INDEX idx_accounts_credential ON accounts(credential_ref);
ALTER TABLE messages ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes >= 0);
ALTER TABLE messages ADD COLUMN parse_status TEXT NOT NULL DEFAULT 'ok'
  CHECK(parse_status IN ('ok','malformed','oversized'));
CREATE TABLE mail_folders (
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  wire_name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  selectable INTEGER NOT NULL CHECK(selectable IN (0,1)),
  PRIMARY KEY(account_id,wire_name)
);
