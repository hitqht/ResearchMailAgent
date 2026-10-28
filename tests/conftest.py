from pathlib import Path

import pytest

from researchmail.config import AppPaths
from researchmail.services.workspace import WorkspaceService


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(tmp_path / "data", tmp_path / "logs")
    result.prepare()
    return result


@pytest.fixture
def service(paths: AppPaths) -> WorkspaceService:
    result = WorkspaceService(paths)
    result.initialize()
    return result


@pytest.fixture
def ai(service):
    import json

    from researchmail.llm.models import ModelConfig
    from researchmail.llm.providers import MockProvider
    from researchmail.mail.models import AccountConfig, ParsedMessage
    from researchmail.services.ai_service import AIService
    from researchmail.storage.mail_repository import MailRepository
    from tests.fakes import MemoryVault
    from tests.test_ai_analysis import BODY, valid_result

    mail = MailRepository(service.database)
    account = mail.save_account(AccountConfig(email="ai@example.invalid"), "unused", None)
    mail.start_cursor(account, "INBOX", 1)
    mail.store_message(
        account, "INBOX", 1, 1, ParsedMessage(subject="Revision", body=BODY), 100, None
    )
    mock = MockProvider(json.dumps(valid_result()))
    vault = MemoryVault()
    result = AIService(service.database, vault, lambda config, secret: mock)
    local = result.save_model(
        ModelConfig(
            label="本机", provider="ollama", model="synthetic", base_url="http://127.0.0.1:11434"
        ),
        "",
    )
    cloud = result.save_model(
        ModelConfig(
            label="云端",
            provider="openai_compatible",
            model="synthetic",
            base_url="https://example.invalid/v1",
            auth="bearer",
        ),
        "synthetic-key",
    )
    return result, mock, vault, local, cloud
