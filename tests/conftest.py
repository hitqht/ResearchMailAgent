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
