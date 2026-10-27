from researchmail.mail.models import Folder


class MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, reference: str) -> str:
        return self.values[reference]

    def set(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def delete(self, reference: str) -> None:
        del self.values[reference]


class FakeSession:
    def __init__(self) -> None:
        self.validity = 10
        self.content = {
            1: b"Subject: Synthetic submission\r\nFrom: editor@example.invalid\r\n\r\nHello",
            2: b"Subject: Synthetic revision\r\n\r\nPlease revise",
        }
        self.fetched: list[int] = []
        self.closed = 0

    def folders(self) -> list[Folder]:
        return [
            Folder("INBOX", "INBOX"),
            Folder("Archive", "Archive"),
            Folder("Parent", "Parent", False),
        ]

    def select(self, folder: str) -> int:
        return self.validity

    def uids(self, after: int) -> list[int]:
        return sorted(uid for uid in self.content if uid > after)

    def fetch(self, uid: int) -> tuple[int, bytes | None]:
        self.fetched.append(uid)
        return len(self.content[uid]), self.content[uid]

    def close(self) -> None:
        self.closed += 1
