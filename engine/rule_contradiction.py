"""A rule the person states that contradicts one already in force (design 6.7, "A contradiction pauses").

The assistant says in `contradicts` which active rules a new rule cannot live with. From the person's own words the rule
would apply at once; with a contradiction named it waits, and the person says which wins: the new rule (the old one is
retired), the existing one (the new one is kept out), or both, optionally with a narrower target for the new one.
"""

from __future__ import annotations

from typing import Any, Literal

from engine.ops import RuleAddOp
from engine.records import Scope
from engine.storage import StoreError

Choice = Literal["new", "existing", "both"]

#: The name of the check that holds the rule, so the review and Today can tell this hold from any other.
CHECK = "rule-contradiction"


def contradicted(view: Any, op: RuleAddOp) -> list[Any]:
    """The active rules the op names in `contradicts`, by record id or by name, each once."""
    wanted = {" ".join(name.split()) for name in op.contradicts}
    found, seen = [], set()
    for rule in view.list("rule"):
        named = rule.id in wanted or rule.data.get("name") in wanted
        if named and rule.data.get("status") == "active" and rule.id not in seen:
            seen.add(rule.id)
            found.append(rule)
    return found


def is_held_for(outcome: dict[str, Any]) -> bool:
    """Whether a changeset's outcome waits on this question."""
    return outcome.get("status") == "held" and any(p.get("check") == CHECK for p in outcome.get("problems") or [])


def held_message(rules: list[Any]) -> str:
    """Why the rule waits, for the held line's reason: names the first rule it cannot live with."""
    text = " ".join(str(rules[0].data.get("text") or rules[0].data["name"]).split())
    more = f" (and {len(rules) - 1} more)" if len(rules) > 1 else ""
    return f"contradicts a rule you already have: {text}{more}; choose which one wins"


def answer(
    store: Any,
    cfg: Any,
    changeset_id: str,
    index: int,
    choice: Choice,
    *,
    applies_to: Scope | None = None,
    ws: Any = None,
) -> str | None:
    """Answer a held contradiction. `new` retires the rules it contradicts (one change of its own, whose id is returned
    so the screen's Undo can take it back with the new rule) and applies the new rule; `existing` keeps things as they
    are and the new rule is not kept; `both` applies the new rule beside the others; when the person narrowed it, the
    scope, projects and exceptions of `applies_to` replace the new rule's own and the rest of its target stays."""
    from engine.applier import apply_as_person, decline_held, release, undo
    from engine.ops import CHANGESET

    cs = store.read().get("changeset", changeset_id)
    if cs is None:
        raise StoreError(f"there is no changeset {changeset_id}")
    outcomes = cs.data["ops"]
    if not 0 <= index < len(outcomes) or outcomes[index]["status"] != "held":
        raise StoreError("that item isn't waiting for you")
    if outcomes[index]["op"].get("op") != "rule.add":
        raise StoreError("that item isn't a rule")
    if choice == "existing":
        decline_held(store, changeset_id, index)
        return None
    op = CHANGESET.validate_python({"ops": [outcomes[index]["op"]]}, context={"op_models": store.plugins.ops}).ops[0]
    assert isinstance(op, RuleAddOp)
    instead = None
    if applies_to is not None:
        # Narrowing limits where the new rule applies (its projects); what else its target names stays as it was.
        limited = op.applies_to.model_copy(
            update={"scope": applies_to.scope, "projects": applies_to.projects, "except_": applies_to.except_}
        )
        instead = op.model_copy(update={"applies_to": Scope.model_validate(limited.model_dump(by_alias=True))})
    retired: str | None = None
    if choice == "new":
        old = contradicted(store.read(), op)
        if old:
            retired = apply_as_person(
                store,
                cfg,
                [{"op": "rule.retire", "id": rule.id} for rule in old],
                "Stopped following a rule the new one replaces",
            )
    try:
        release(store, cfg, changeset_id, index, ws=ws, instead=instead)
    except StoreError:
        if retired is not None:
            undo(store, retired)  # the new rule didn't go in, so the old one stays in force
        raise
    return retired
