"""Opt-in real Ollama smoke using isolated synthetic data, never the user's mailbox."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from researchmail.config import AppPaths
from researchmail.llm.models import AIError, ModelConfig
from researchmail.mail.models import AccountConfig, ParsedMessage
from researchmail.services.ai_service import AIService
from researchmail.services.workspace import WorkspaceService
from researchmail.storage.mail_repository import MailRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="An already installed local Ollama model")
    parser.add_argument("--output", type=Path, default=Path("artifacts/real-ollama.json"))
    args = parser.parse_args()
    started = time.monotonic()
    report: dict[str, object] = {
        "model": args.model,
        "synthetic_data": True,
        "real_mail_sent": False,
    }
    with tempfile.TemporaryDirectory(prefix="researchmail-ollama-") as directory:
        root = Path(directory)
        workspace = WorkspaceService(AppPaths(root / "data", root / "logs"))
        workspace.initialize()
        ai = AIService(workspace.database)
        model = ai.save_model(
            ModelConfig(
                label="Synthetic local smoke",
                provider="ollama",
                model=args.model,
                base_url="http://127.0.0.1:11434",
            ),
            "",
        )
        try:
            ai.test_connection(model)
            report["connection"] = "passed"
            repo = MailRepository(workspace.database)
            account = repo.save_account(
                AccountConfig(email="synthetic@example.invalid"), "unused", None
            )
            repo.start_cursor(account, "INBOX", 1)
            repo.store_message(
                account,
                "INBOX",
                1,
                1,
                ParsedMessage(
                    subject="Manuscript revision request (synthetic fixture)",
                    body="Dear author, please submit your revised manuscript by 2026-11-30. "
                    "Best, Editorial Office.",
                ),
                200,
                None,
            )
            result = ai.analyze(1, model)
            report.update(analysis="passed", result=result.model_dump(mode="json"))
        except AIError as error:
            report["error"] = error.code
    report["seconds"] = round(time.monotonic() - started, 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("analysis") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
