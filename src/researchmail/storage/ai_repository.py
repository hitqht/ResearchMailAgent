"""Local AI metadata, validated analyses and proposed tasks; no secrets or raw responses."""

import hashlib
import json
from datetime import date, timedelta
from typing import cast

from researchmail.llm.models import (
    AIError,
    Analysis,
    ModelConfig,
    Preferences,
    SavedModel,
    TaskRecord,
    TaskSuggestion,
)
from researchmail.research_skills import ResearchSkill, load_skill
from researchmail.storage.database import Database


class AIRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def models(self) -> list[SavedModel]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM model_configs ORDER BY id").fetchall()
        return [
            SavedModel(
                id=r["id"],
                config=ModelConfig.model_validate_json(r["config_json"]),
                credential_ref=r["credential_ref"],
            )
            for r in rows
        ]

    def model(self, model_id: int) -> SavedModel:
        value = next((m for m in self.models() if m.id == model_id), None)
        if value is None:
            raise AIError("missing")
        return value

    def save_model(self, config: ModelConfig, reference: str | None, model_id: int | None) -> int:
        with self.database.transaction() as conn:
            if model_id is None:
                cur = conn.execute(
                    "INSERT INTO model_configs(config_json,credential_ref) VALUES (?,?)",
                    (config.model_dump_json(), reference),
                )
                model_id = cast(int, cur.lastrowid)
            else:
                cur = conn.execute(
                    "UPDATE model_configs SET config_json=?,credential_ref=? WHERE id=?",
                    (config.model_dump_json(), reference, model_id),
                )
                if cur.rowcount != 1:
                    raise AIError("missing")
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) "
                "VALUES ('model_saved','model',?,'success')",
                (model_id,),
            )
        return model_id

    def preferences(self) -> Preferences:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM ai_preferences WHERE singleton=1").fetchone()
        return Preferences(
            default_model_id=row["default_model_id"],
            local_first=bool(row["local_first"]),
            reminders=bool(row["reminders"]),
            reminder_days=row["reminder_days"],
        )

    def save_preferences(self, prefs: Preferences) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE ai_preferences SET default_model_id=?,local_first=?,reminders=?,"
                "reminder_days=? WHERE singleton=1",
                (
                    prefs.default_model_id,
                    int(prefs.local_first),
                    int(prefs.reminders),
                    prefs.reminder_days,
                ),
            )

    def source(self, message_id: int) -> str:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT subject,sender,body_text,attachments_json,parse_status "
                "FROM messages WHERE id=?",
                (message_id,),
            ).fetchone()
        if row is None or row["parse_status"] != "ok":
            raise AIError("config")
        # Stable serialization is also used to bind a one-shot cloud consent to exact content.
        return json.dumps(
            {k: row[k] for k in ("subject", "sender", "body_text", "attachments_json")},
            ensure_ascii=False,
        )

    def evidence_source(self, message_id: int) -> str:
        data = json.loads(self.source(message_id))
        return "\n".join((data["subject"], data["sender"], data["body_text"]))

    def store_analysis(
        self, message_id: int, model: SavedModel, skill: ResearchSkill, result: Analysis
    ) -> int:
        with self.database.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO analyses(message_id,skill_name,skill_version,model_name,"
                "category,confidentiality,result_json,confidence,status,model_config_id,"
                "skill_digest) VALUES (?,?,?,?,?,?,?,?,'validated',?,?)",
                (
                    message_id,
                    skill.name,
                    skill.version,
                    model.config.model,
                    result.category,
                    result.confidentiality,
                    result.model_dump_json(),
                    result.confidence,
                    model.id,
                    skill.digest,
                ),
            )
            analysis_id = cast(int, cur.lastrowid)
            for task in result.tasks:
                key = hashlib.sha256(
                    json.dumps(
                        [
                            message_id,
                            task.deadline_kind,
                            task.title.strip().casefold(),
                            str(task.deadline),
                        ],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                conn.execute(
                    "INSERT INTO tasks(message_id,title,deadline,deadline_kind,evidence,"
                    "dedupe_key) VALUES (?,?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING",
                    (
                        message_id,
                        task.title,
                        str(task.deadline) if task.deadline else None,
                        task.deadline_kind,
                        task.evidence,
                        key,
                    ),
                )
            conn.execute("UPDATE messages SET status='analyzed' WHERE id=?", (message_id,))
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) "
                "VALUES ('analysis_saved','message',?,'success')",
                (message_id,),
            )
        return analysis_id

    def analyses(self, message_id: int | None = None) -> list[dict[str, object]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT a.id,a.message_id,a.result_json,a.skill_name,a.skill_version,"
                "m.subject FROM analyses a JOIN messages m ON m.id=a.message_id "
                "WHERE (? IS NULL OR a.message_id=?) AND a.status='validated' "
                "AND a.id=(SELECT max(b.id) FROM analyses b WHERE b.message_id=a.message_id "
                "AND b.status='validated') ORDER BY a.id DESC LIMIT 100",
                (message_id, message_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def tasks(self) -> list[TaskRecord]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT id,message_id,title,deadline,deadline_kind,evidence,status "
                "FROM tasks ORDER BY deadline IS NULL,deadline,id LIMIT 1000"
            ).fetchall()
        return [TaskRecord.model_validate(dict(r)) for r in rows]

    def create_task(self, task: TaskSuggestion, message_id: int | None = None) -> int:
        # This entry point is for explicit UI/user tool calls, never model output execution.
        key = hashlib.sha256(
            json.dumps([message_id, task.model_dump(mode="json")], sort_keys=True).encode()
        ).hexdigest()
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO tasks(message_id,title,deadline,deadline_kind,evidence,dedupe_key) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING",
                (
                    message_id,
                    task.title,
                    str(task.deadline) if task.deadline else None,
                    task.deadline_kind,
                    task.evidence,
                    key,
                ),
            )
            row = conn.execute("SELECT id FROM tasks WHERE dedupe_key=?", (key,)).fetchone()
        return int(row[0])

    def update_task(
        self, task_id: int, status: str, deadline: date | None = None, edit_deadline: bool = False
    ) -> None:
        if status not in {"suggested", "confirmed", "done", "dismissed"}:
            raise AIError("config")
        with self.database.transaction() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status=?,deadline=CASE WHEN ? THEN ? ELSE deadline END,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (status, int(edit_deadline), str(deadline) if deadline else None, task_id),
            )
            if cur.rowcount != 1:
                raise AIError("config")
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) "
                "VALUES ('task_updated','task',?,'success')",
                (task_id,),
            )

    def audit(self, event: str, entity_id: int | None, outcome: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_events(event,entity_type,entity_id,outcome) "
                "VALUES (?,'message',?,?)",
                (event, entity_id, outcome),
            )

    def digest(self, today: date | None = None) -> str:
        load_skill("daily-digest")
        today = today or date.today()
        prefs = self.preferences()
        tasks = [t for t in self.tasks() if t.status == "confirmed"]
        due = [
            t
            for t in tasks
            if t.deadline is not None and t.deadline <= today + timedelta(days=prefs.reminder_days)
        ]
        lines = [
            f"{today.isoformat()} · 本地任务日报",
            f"已确认 {len(tasks)} 项 · 近期或逾期 {len(due)} 项",
            "应用关闭时不提供提醒。日期按本机日历显示，未知日期需人工确认。",
        ]
        for task in tasks:
            marker = " · 逾期" if task.deadline is not None and task.deadline < today else ""
            lines.append(
                f"#{task.id} {task.title} · {task.deadline or '日期待确认'}{marker}"
                f"\n来源邮件 #{task.message_id or '手工'} · {task.evidence or '无证据'}"
            )
        return "\n\n".join(lines)
