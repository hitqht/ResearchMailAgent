"""Application-owned paths; no credentials or network settings in the repository."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    data: Path
    logs: Path

    @classmethod
    def default(cls) -> "AppPaths":
        home = Path.home()
        return cls(
            data=home / "Library/Application Support/ResearchMailAgent",
            logs=home / "Library/Logs/ResearchMailAgent",
        )

    @property
    def database(self) -> Path:
        return self.data / "researchmail.sqlite3"

    def prepare(self) -> None:
        for directory in (self.data, self.logs):
            if directory.is_symlink():
                raise OSError("Application directory must not be a symbolic link")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
