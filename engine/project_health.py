"""What the app can see about a project beside the status the person typed (design 7.13): overdue to-dos, weeks with no
change, and a target day that has passed. When the typed status says all is well and one of these says otherwise, the
projects list marks the status with the reasons and offers Update status. Nothing here changes a status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

#: The meanings of a status that say all is well, so a sign of trouble beside them is a disagreement.
FINE = ("open", "not_started")


@dataclass
class Health:
    """What the app sees: the counts behind the words, and whether they disagree with the typed status."""

    overdue: int = 0
    quiet_weeks: int | None = None
    target_passed: bool = False
    disagrees: bool = False


def read(
    *,
    meaning: str | None,
    overdue: int,
    last_change: str | None,
    target: str | None,
    today: date,
    quiet_after_weeks: int,
) -> Health:
    """The health of one project. `meaning` is what its typed status means (none when it has no status); a finished
    project, and one whose status already says it is at risk or blocked, never disagrees."""
    quiet: int | None = None
    if last_change:
        try:
            quiet = max(0, (today - datetime.fromisoformat(last_change).date()).days // 7)
        except ValueError:
            quiet = None
    passed = False
    if target:
        try:
            passed = date.fromisoformat(str(target)) < today
        except ValueError:
            passed = False
    found = Health(overdue=overdue, quiet_weeks=quiet, target_passed=passed)
    trouble = overdue > 0 or (quiet is not None and quiet >= quiet_after_weeks) or passed
    found.disagrees = trouble and meaning in FINE
    return found
