import os
import sys

from PySide6.QtWidgets import QApplication

from researchmail import __version__
from researchmail.config import AppPaths
from researchmail.eventlog import EventLog
from researchmail.gui.window import MainWindow, startup_error
from researchmail.services.workspace import WorkspaceService


def main() -> int:
    os.umask(0o077)
    app = QApplication(sys.argv)
    app.setApplicationName("ResearchMailAgent")
    app.setApplicationDisplayName("ResearchMail Agent")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("ResearchMailAgent")
    paths = AppPaths.default()
    try:
        paths.prepare()
        event_log = EventLog(paths.logs)
    except OSError:
        startup_error()
        return 1
    window = MainWindow(WorkspaceService(paths), event_log)
    window.show()
    try:
        return app.exec()
    finally:
        event_log.close()
