"""The same answer twice (design 6.22): when the person gives the same answer to questions of one kind about one subject
(two routing questions in one project answered with the same person), the correction's learning request is told so and
asked for the routing entry or rule the two answers imply, once. A plain function only finds the repeat and whether the
proposal is still wanted; what the entry says is the assistant's.

Not offered again for a subject once an entry for it is waiting, active or was declined: the person decided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: The kinds of knowledge entry an answer given twice may imply.
ENTRY_KINDS = ("routing_entry", "rule")


@dataclass(frozen=True)
class Repeat:
    kind: str  # the kind of question
    project: str  # the subject: the project the questions are about
    answer: str  # the answer, as the person gave it
    questions: list[str]  # the questions it was given to, newest first, the corrected one first


def _same(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _subject(data: dict[str, Any]) -> str | None:
    projects = data.get("projects") or []
    return projects[0] if projects else None


def _decided(view: Any, project: str) -> bool:
    """Whether an entry about this subject is waiting, active or declined, so the answers are not offered again."""
    for kind in ENTRY_KINDS:
        for entry in view.list(kind):
            if entry.data.get("status") in ("proposed", "active", "discarded") and project in (
                (entry.data.get("applies_to") or {}).get("projects") or []
            ):
                return True
    return False


def find(view: Any, question_id: str) -> Repeat | None:
    """The repeat the answer to this question makes, or None: it was answered, another question of its kind about its
    project was answered the same way, and no entry for that project is waiting, active or declined."""
    question = view.get("question", question_id)
    if question is None or question.data.get("status") != "answered" or not _same(question.data.get("answer")):
        return None
    project = _subject(question.data)
    if project is None:
        return None
    others = [
        q
        for q in view.list("question")
        if q.id != question_id
        and q.data.get("status") == "answered"
        and q.data.get("kind") == question.data.get("kind")
        and _subject(q.data) == project
        and _same(q.data.get("answer")) == _same(question.data.get("answer"))
    ]
    if not others or _decided(view, project):
        return None
    ordered = sorted(others, key=lambda q: int(re.search(r"(\d+)$", q.id).group(1)), reverse=True)  # type: ignore[union-attr]
    return Repeat(question.data["kind"], project, str(question.data["answer"]), [question_id, *[q.id for q in ordered]])
