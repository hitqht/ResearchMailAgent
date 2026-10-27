from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from researchmail import app
from researchmail.config import AppPaths


def test_main_lifecycle(
    qapp: QApplication, paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    qt_app = MagicMock()
    qt_app.exec.return_value = 0
    log = MagicMock()
    window = MagicMock()
    monkeypatch.setattr(app, "QApplication", lambda _: qt_app)
    monkeypatch.setattr(app.AppPaths, "default", lambda: paths)
    monkeypatch.setattr(app, "EventLog", lambda _: log)
    monkeypatch.setattr(app, "MainWindow", lambda *args: window)
    assert app.main() == 0
    window.show.assert_called_once()
    log.close.assert_called_once()


def test_main_path_failure_has_user_message(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    qt_app = MagicMock()
    paths = MagicMock()
    paths.prepare.side_effect = OSError("private fixture")
    message = MagicMock()
    monkeypatch.setattr(app, "QApplication", lambda _: qt_app)
    monkeypatch.setattr(app.AppPaths, "default", lambda: paths)
    monkeypatch.setattr(app, "startup_error", message)
    assert app.main() == 1
    message.assert_called_once_with()
    qt_app.exec.assert_not_called()
