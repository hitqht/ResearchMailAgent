"""Opt-in local-model draft generation with synthetic data; never calls SMTP."""

import argparse
import json
import tempfile
from pathlib import Path

from researchmail.config import AppPaths
from researchmail.llm.models import AIError, ModelConfig
from researchmail.mail.models import AccountConfig, ParsedMessage
from researchmail.services.ai_service import AIService
from researchmail.services.draft_service import DraftService
from researchmail.services.workspace import WorkspaceService
from researchmail.storage.mail_repository import MailRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/local-draft.json"))
    args = parser.parse_args()
    report: dict[str, object] = {"synthetic_data": True, "model": args.model, "smtp_requests": 0}
    with tempfile.TemporaryDirectory(prefix="researchmail-draft-") as directory:
        root = Path(directory)
        ws = WorkspaceService(AppPaths(root / "data", root / "logs"))
        ws.initialize()
        mail = MailRepository(ws.database)
        account = mail.save_account(AccountConfig(email="preview@example.invalid"), "unused", None)
        mail.start_cursor(account, "INBOX", 1)
        mail.store_message(
            account,
            "INBOX",
            1,
            1,
            ParsedMessage(
                subject="Synthetic revision request",
                sender="editor@example.invalid",
                body="Please clarify which revision details you need.",
            ),
            100,
            None,
        )
        ai = AIService(ws.database)
        model = ai.save_model(
            ModelConfig(
                label="Local smoke",
                model=args.model,
                provider="ollama",
                base_url="http://127.0.0.1:11434",
            ),
            "",
        )
        drafts = DraftService(ws.database, ai=ai)
        try:
            draft = drafts.repository.get(
                drafts.create_reply(
                    1, "礼貌询问具体需要修改的章节。不要承诺完成时间。", model, True
                )
            )
            report.update(
                ok=True,
                status=draft.status,
                subject=draft.content.subject,
                body=draft.content.body,
                recipients=draft.content.recipients,
            )
        except AIError as error:
            report.update(ok=False, error=error.code)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
