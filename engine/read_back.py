"""The read-back for a rule the person states (design 6.7): four short lines computed from the rule's structured target
(`applies_to`) and the store, with no AI, so a misreading shows before it matters.

1. what it applies to: the record types and fields, the filter, the projects and people, or everywhere;
2. what it doesn't change: the nearest neighbors the person might assume it covers (at most three);
3. what it overlaps with: each active rule whose target intersects this one;
4. what it would change right now: the count of the current open records the target matches, and the first few.

The result is plain data (it is stored on the change's outcome and sent as it is), worded on screen from the wording
sheet. Reads only; nothing here writes.
"""

from __future__ import annotations

from typing import Any

from engine.projects import chain, project_of
from engine.records import REGISTRY, Scope, kind_label

#: How many neighbors line 2 lists, and how many matched records line 4 lists before "and so on".
MOST_UNCHANGED = 3
MOST_ITEMS = 25

#: A record in one of these states is finished, so a dry run doesn't count it. A kind with no `status` is always
#: current.
CLOSED = frozenset(
    {
        "done",
        "dropped",
        "closed",
        "answered",
        "retired",
        "discarded",
        "expired",
        "undone",
        "archived",
        "superseded",
        "cancelled",
        "called_off",
    }
)


def _target(entry: str) -> tuple[str, str | None]:
    """A record target (`kind` or `kind.field`) as its kind and its field."""
    kind, _, field = entry.partition(".")
    return kind, field or None


def _holds(value: Any, wanted: Any) -> bool:
    """Whether a stored value is, or contains, the wanted one (any of them, when a list is wanted)."""
    if isinstance(wanted, list):
        return any(_holds(value, each) for each in wanted)
    if isinstance(value, list):
        return any(_holds(each, wanted) for each in value)
    if isinstance(value, dict):
        return any(_holds(each, wanted) for each in value.values())
    return value == wanted


def _mentions(data: Any, people: list[str]) -> bool:
    return any(_holds(data, person) for person in people)


def _is_open(data: dict[str, Any]) -> bool:
    return data.get("status") not in CLOSED


def _in_projects(view: Any, record: Any, scope: Scope) -> bool:
    """Whether a record is inside the projects a target names (a project inside a project counts), or outside the
    ones it leaves out."""
    inside = {p.id for p in chain(view, project_of(record))}
    if scope.scope == "projects":
        return bool(inside & set(scope.projects))
    return not (inside & set(scope.except_))


def _matches(view: Any, record: Any, scope: Scope, field: str | None) -> bool:
    data = record.data
    if not _is_open(data):
        return False
    if field is not None and data.get(field) in (None, "", [], {}):
        return False
    if any(not _holds(data.get(key), wanted) for key, wanted in scope.filter.items()):
        return False
    if (scope.scope == "projects" or scope.except_) and not _in_projects(view, record, scope):
        return False
    return not (scope.people and not _mentions(data, scope.people))


def _title(record: Any) -> str:
    data = record.data
    return " ".join(str(data.get("text") or data.get("title") or data.get("name") or record.id).split())


def _count(view: Any, scope: Scope) -> tuple[int, list[dict[str, str]]]:
    """The open records the target matches now: how many, and the first few as kind, id and words."""
    total, items = 0, []
    seen: set[tuple[str, str]] = set()
    for entry in scope.records:
        kind, field = _target(entry)
        for record in view.list(kind):
            if (kind, record.id) in seen or not _matches(view, record, scope, field):
                continue
            seen.add((kind, record.id))
            total += 1
            if len(items) < MOST_ITEMS:
                items.append({"kind": kind, "id": record.id, "title": _title(record)})
    return total, items


def _named(view: Any, project: str) -> dict[str, str]:
    found = view.get("project", project)
    return {"id": project, "name": str(found.data.get("name") or project) if found is not None else project}


def _applies(view: Any, models: dict[str, Any], scope: Scope, people: Any) -> dict[str, Any]:
    targets = []
    for entry in scope.records:
        kind, field = _target(entry)
        targets.append({"kind": kind, "kind_label": kind_label(models.get(kind), kind), "field": field})
    return {
        "everywhere": not (scope.records or scope.task_kinds or scope.filter or scope.people)
        and scope.scope == "workspace"
        and not scope.except_,
        "targets": targets,
        "filter": [{"field": key, "value": _plain(value)} for key, value in scope.filter.items()],
        "projects": [_named(view, p) for p in scope.projects],
        "except": [_named(view, p) for p in scope.except_],
        "people": [{"id": p, "name": people.name(p) if people is not None else p} for p in scope.people],
        "task_kinds": list(scope.task_kinds),
    }


def _plain(value: Any) -> str:
    return ", ".join(str(each) for each in value) if isinstance(value, list) else str(value)


#: The record types the person's own work is made of. A neighbor is one of these or one a plugin added, never an
#: internal record such as a draft or a run.
WORK_KINDS = frozenset({"action", "question", "fact", "event", "note", "project", "person"})


def _unchanged(view: Any, models: dict[str, Any], tasks: list[str], scope: Scope) -> list[dict[str, Any]]:
    """The nearest things the target leaves out, a few of each of three kinds in turn: the same field on other record
    types, the projects outside the ones it names, and the task kinds outside the ones it names."""
    fields: list[dict[str, Any]] = []
    for entry in scope.records:
        kind, field = _target(entry)
        if field is None:
            continue
        for other, model in models.items():
            work = other in WORK_KINDS or other not in REGISTRY
            if work and other != kind and field in getattr(model, "model_fields", {}):
                fields.append({"why": "field", "kind": other, "kind_label": kind_label(model, other), "field": field})
    if scope.scope == "projects":
        left = [p.id for p in view.list("project") if p.id not in scope.projects]
    else:
        left = list(scope.except_)
    projects = [{"why": "project", **_named(view, p)} for p in left]
    kinds = (
        [{"why": "task_kind", "name": name} for name in tasks if name not in scope.task_kinds]
        if scope.task_kinds
        else []
    )
    chosen: list[dict[str, Any]] = []
    rounds = [list(fields), projects, kinds]
    while len(chosen) < MOST_UNCHANGED and any(rounds):
        for each in rounds:
            if each and len(chosen) < MOST_UNCHANGED:
                chosen.append(each.pop(0))
    return chosen


def _records_meet(mine: Scope, theirs: Scope) -> bool:
    """Whether two targets name the same record type or field: a type meets its own fields, two fields meet only when
    they are the same field. A target naming no record type is about the work as a whole, which meets only another
    like it."""
    if bool(mine.records) != bool(theirs.records):
        return False
    if not mine.records:
        return not (mine.task_kinds and theirs.task_kinds) or bool(set(mine.task_kinds) & set(theirs.task_kinds))
    for a in mine.records:
        for b in theirs.records:
            (ka, fa), (kb, fb) = _target(a), _target(b)
            if ka == kb and (fa is None or fb is None or fa == fb):
                return True
    return False


def _filters_meet(mine: Scope, theirs: Scope) -> bool:
    """False when both filter the same field to different values: nothing is in both."""
    return not any(
        key in theirs.filter and not (_holds(theirs.filter[key], wanted) or _holds(wanted, theirs.filter[key]))
        for key, wanted in mine.filter.items()
    )


def _projects_meet(view: Any, mine: Scope, theirs: Scope) -> bool:
    """Whether two targets can reach the same project: the whole workspace meets everything, less what it leaves out."""
    if mine.scope == "projects" and theirs.scope == "projects":
        return bool(set(mine.projects) & set(theirs.projects))
    if mine.scope == "projects":
        return bool(set(mine.projects) - set(theirs.except_))
    if theirs.scope == "projects":
        return bool(set(theirs.projects) - set(mine.except_))
    return True


def _people_meet(mine: Scope, theirs: Scope) -> bool:
    return not (mine.people and theirs.people) or bool(set(mine.people) & set(theirs.people))


def overlapping(view: Any, scope: Scope, constrains: list[str], exclude: set[str]) -> list[dict[str, str]]:
    """Each active rule whose target intersects this one: the same record type or field (or the same op field it
    constrains), the same filter value, and a project and person both can reach. Each by its id, name and words."""
    found = []
    for rule in view.list("rule"):
        data = rule.data
        if rule.id in exclude or data.get("status") != "active":
            continue
        theirs = Scope.model_validate(data.get("applies_to") or {})
        same_op_field = bool(set(constrains) & set(data.get("constrains") or []))
        if not (
            (same_op_field or _records_meet(scope, theirs))
            and _filters_meet(scope, theirs)
            and _projects_meet(view, scope, theirs)
            and _people_meet(scope, theirs)
        ):
            continue
        found.append({"id": rule.id, "name": data["name"], "text": " ".join(str(data.get("text") or "").split())})
    return found


def read_back(
    store: Any,
    view: Any,
    scope: Scope,
    constrains: list[str] | None = None,
    *,
    exclude: set[str] | None = None,
    people: Any = None,
) -> dict[str, Any]:
    """The four lines for a rule with this target, as plain data. `exclude` holds the record ids of rules that don't
    count as overlaps (the rule itself, once it is a record). `count` is None when the target names no record type:
    the rule is about how work is done, so there is nothing to count."""
    models = store.plugins.records
    count, items = _count(view, scope) if scope.records else (None, [])
    return {
        "applies": _applies(view, models, scope, people),
        "unchanged": _unchanged(view, models, sorted(store.plugins.tasks), scope),
        "overlaps": overlapping(view, scope, constrains or [], exclude or set()),
        "count": count,
        "items": items,
        "matches_nothing": count == 0,
    }
