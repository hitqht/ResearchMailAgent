CREATE TABLE app_settings (
    key TEXT PRIMARY KEY CHECK(key IN ('onboarding_completed')),
    value TEXT NOT NULL CHECK(value IN ('true','false')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
