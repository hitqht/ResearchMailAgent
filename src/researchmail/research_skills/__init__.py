"""Versioned project instructions, packaged unchanged from the root skills directory."""

import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files

from researchmail.llm.models import AIError, Category

NAMES = (
    "email-triage",
    "paper-submission",
    "manuscript-revision",
    "peer-review",
    "collaboration",
    "institutional-notice",
    "daily-digest",
)
CATEGORY_SKILL = {
    Category.SUBMISSION: "paper-submission",
    Category.REVISION: "manuscript-revision",
    Category.INVITATION: "peer-review",
    Category.REVIEW: "peer-review",
    Category.COLLABORATION: "collaboration",
    Category.NOTICE: "institutional-notice",
    Category.OTHER: "email-triage",
}


@dataclass(frozen=True)
class ResearchSkill:
    name: str
    version: str
    text: str
    digest: str


def load_skill(name: str) -> ResearchSkill:
    if name not in NAMES:
        raise AIError("config")
    try:
        text = files(__package__).joinpath(name, "SKILL.md").read_text(encoding="utf-8")
        header = text.split("---", 2)[1]
        if f"name: {name}\n" not in header:
            raise ValueError("Invalid name")
        match = re.search(r'^  version: "(\d+\.\d+\.\d+)"$', header, re.MULTILINE)
        if match is None:
            raise ValueError("Missing version")
        return ResearchSkill(name, match[1], text, hashlib.sha256(text.encode()).hexdigest())
    except (OSError, ValueError, IndexError):
        raise AIError("config") from None
