"""The open items a correction's rule could reach (design 6.22).

When the person corrects one question or to-do with a rule ("all of these go to Ana", "this kind of work isn't mine"),
the request carries, after that item, the other open questions, to-dos and drafts for the same person, the same
project or the same source, so the assistant can change every one the rule covers in the same change. A plain function
only narrows what the assistant looks at: whether the rule covers an item is the assistant's to say.
"""

from __future__ import annotations

import re
from typing import Any

#: The kinds of item whose correction can state a rule that reaches others.
REACHING = ("action", "question")
#: Where each kind of open item stands while it is open.
OPEN = {"question": ("open", "sent"), "action": ("open", "held"), "act": ("draft",)}


def _number(record_id: str) -> int:
    found = re.search(r"(\d+)$", record_id)
    return int(found.group(1)) if found else 0


def _people(kind: str, data: dict[str, Any]) -> set[str]:
    if kind == "question":
        return {data["to"]} if data.get("to") else set()
    if kind == "action":
        return {o["person"] for o in data.get("owners") or [] if o.get("person")}
    return {r["person"] for r in (data.get("target") or {}).get("recipients") or [] if r.get("person")}


def _projects(kind: str, data: dict[str, Any]) -> set[str]:
    if kind == "question":
        return set(data.get("projects") or [])
    return {data["project"]} if data.get("project") else set()


def _sources(kind: str, data: dict[str, Any]) -> set[str]:
    if kind == "act":
        return set(data.get("sources") or [])
    return {data["source"]} if data.get("source") else set()


def reach(store: Any, kind: str, record_id: str, limit: int) -> list[tuple[str, str]]:
    """The other open items that share a person, a project or a source with the corrected item, newest first, as
    (kind, id), at most `limit`. Empty for a kind of item whose correction states no rule, or when `limit` is 0."""
    view = store.read()
    corrected = view.get(kind, record_id) if kind in REACHING and limit > 0 else None
    if corrected is None:
        return []
    people, projects, sources = (f(kind, corrected.data) for f in (_people, _projects, _sources))
    found = []
    for other_kind, states in OPEN.items():
        for record in view.list(other_kind):
            if (other_kind, record.id) == (kind, record_id) or record.data.get("status") not in states:
                continue
            data = record.data
            if (
                people & _people(other_kind, data)
                or projects & _projects(other_kind, data)
                or sources & _sources(other_kind, data)
            ):
                found.append((other_kind, record.id))
    found.sort(key=lambda item: _number(item[1]), reverse=True)
    return found[:limit]
