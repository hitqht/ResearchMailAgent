CREATE TABLE model_configs (
    id INTEGER PRIMARY KEY,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    credential_ref TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE ai_preferences (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    default_model_id INTEGER REFERENCES model_configs(id) ON DELETE SET NULL,
    local_first INTEGER NOT NULL DEFAULT 1 CHECK(local_first IN (0,1)),
    reminders INTEGER NOT NULL DEFAULT 0 CHECK(reminders IN (0,1)),
    reminder_days INTEGER NOT NULL DEFAULT 3 CHECK(reminder_days BETWEEN 0 AND 30)
);
INSERT INTO ai_preferences(singleton) VALUES(1);
ALTER TABLE analyses ADD COLUMN model_config_id INTEGER REFERENCES model_configs(id);
ALTER TABLE analyses ADD COLUMN skill_digest TEXT;
CREATE INDEX idx_analyses_latest ON analyses(message_id,id DESC);
