"""Conservative dates: require an explicit full calendar date inside the exact quote."""

import contextlib
import re
from datetime import date

from researchmail.llm.models import AIError, Analysis, Category


def explicit_dates(quote: str) -> set[date]:
    values: set[date] = set()
    for year, month, day in re.findall(
        r"(?<!\d)(\d{4})(?:-|/|年)(\d{1,2})(?:-|/|月)(\d{1,2})(?:日)?(?!\d)", quote
    ):
        with contextlib.suppress(ValueError):
            values.add(date(int(year), int(month), int(day)))
    months = "January February March April May June July August September October November December"
    for index, name in enumerate(months.split(), 1):
        month_name = rf"(?:{name}|{name[:3]}\.?)"
        patterns = (
            rf"\b{month_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
            rf"\b(\d{{1,2}})\s+{month_name},?\s+(\d{{4}})\b",
        )
        for pattern in patterns:
            for day, year in re.findall(pattern, quote, re.IGNORECASE):
                with contextlib.suppress(ValueError):
                    values.add(date(int(year), index, int(day)))
    return values


def validate_evidence(result: Analysis, source: str) -> None:
    quotes = (*result.evidence, *(task.evidence for task in result.tasks))
    if any(not quote.strip() or quote not in source for quote in quotes):
        raise AIError("response")
    allowed = {
        Category.INVITATION: {"invitation_response", "other"},
        Category.REVIEW: {"review_report", "other"},
        Category.REVISION: {"revision", "proof", "other"},
        Category.SUBMISSION: {"proof", "other"},
        Category.COLLABORATION: {"other"},
        Category.NOTICE: {"other"},
        Category.OTHER: {"other"},
    }
    for task in result.tasks:
        if task.deadline_kind not in allowed[result.category]:
            raise AIError("response")
        # More than one date in a quote is ambiguous. Never guess year or timezone.
        if task.deadline is not None and explicit_dates(task.evidence) != {task.deadline}:
            raise AIError("response")
