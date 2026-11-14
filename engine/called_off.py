"""A called-off calendar entry is held, not done (design 6.33, "Called off is held, not done").

An entry that is called off (the calendar's own cancellation, or the person's own Call off) keeps its place and waits
for a new date. The to-dos tied to it (`due_event`) are put on hold by the same change and come back, with the
entry's new date, in the change that moves it. When the person drops the entry (with a reason, never counted as done
or as missed) one line asks what to do with the to-dos still held for it: keep them, with no date, or drop them with the
entry's reason. The core only moves its own records and never writes the person's calendar.

`sync` is what the applier calls inside the change that edits an entry, so one change, one Undo.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from engine import sides
from engine.storage import StoreError, WriteContext

WAITING_KEY = "entry.called_off.waiting"
_WRITER = WriteContext(actor="pm", trust="trusted", op="record.edit")


def waiting_text(cfg: Any, title: str) -> str:
    """What a to-do waits for while the entry it is tied to is called off."""
    return sides.word(cfg, WAITING_KEY).format(title=" ".join(title.split()))


def is_held(data: dict[str, Any]) -> bool:
    """Whether an entry is called off and waits for a new date: not dropped, and not a reminder or a delivery."""
    return (
        bool(data.get("cancelled"))
        and not data.get("dropped")
        and not data.get("reminder")
        and not data.get("delivery")
    )


def sync(tx: Any, event_id: str, w: WriteContext, cfg: Any = None) -> list[str]:
    """Bring the to-dos tied to an entry in step with what happened to it: called off, they are put on hold; with a new
    date (called off no more), the holds this entry made end. A to-do the person held for another reason is never
    touched. Returns the to-dos changed."""
    entry = tx.get("event", event_id)
    if entry is None:
        return []
    held = is_held(entry.data)
    dropped = bool(entry.data.get("dropped"))
    since = date.fromisoformat(tx._clock()[:10])
    changed = []
    for action in tx.find("action", {"due_event": event_id}):
        data = action.data
        if data["status"] != "open":
            continue
        hold = data.get("on_hold")
        if held and not hold:
            put = {"waiting_for": waiting_text(cfg, entry.data["title"]), "since": since.isoformat(), "entry": event_id}
            tx.update("action", action.id, {"on_hold": put}, w, read_version=action.version)
            changed.append(action.id)
        elif not held and not dropped and hold and hold.get("entry") == event_id:
            tx.update("action", action.id, {"on_hold": None}, w, read_version=action.version)
            changed.append(action.id)
    return changed


def held_entries(view: Any, today: date) -> list[Any]:
    """The called-off entries that wait for a new date and haven't passed, soonest first."""
    found = [e for e in view.list("event") if is_held(e.data) and str(e.data["start"])[:10] >= today.isoformat()]
    return sorted(found, key=lambda e: (str(e.data["start"]), e.id))


def held_todos(view: Any, entry_id: str) -> list[Any]:
    """The open to-dos on hold because this entry was called off."""
    return [
        a
        for a in view.find("action", {"due_event": entry_id})
        if a.data["status"] == "open" and (a.data.get("on_hold") or {}).get("entry") == entry_id
    ]


def asking_about_todos(view: Any) -> list[Any]:
    """The dropped entries that still have to-dos held for them: one line asks what to do with them."""
    return sorted(
        (e for e in view.list("event") if e.data.get("dropped") and held_todos(view, e.id)), key=lambda e: e.id
    )


def _entry(store: Any, entry_id: str) -> Any:
    found = store.read().get("event", entry_id)
    if found is None:
        raise StoreError("There is no such calendar entry.")
    return found


def _edit(entry: Any, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": "record.edit",
        "record": {"kind": "event", "id": entry.id},
        "fields": fields,
        "read_version": entry.version,
    }


def call_off(store: Any, cfg: Any, entry_id: str) -> str:
    """The person calls an entry off: it is held, with its tied to-dos. Returns the changeset's id (Undo takes it)."""
    from engine.applier import apply_as_person

    entry = _entry(store, entry_id)
    if entry.data.get("cancelled"):
        raise StoreError("That entry is called off already.")
    return apply_as_person(store, cfg, [_edit(entry, {"cancelled": True})], f"Called off {entry.data['title']}")


def new_date(store: Any, cfg: Any, entry_id: str, start: str, end: str | None = None) -> str:
    """The person gives a called-off entry a new date: it is on again, its tied to-dos come off hold and follow the new
    day, all in one change."""
    from engine.applier import apply_as_person

    entry = _entry(store, entry_id)
    if not is_held(entry.data):
        raise StoreError("That entry isn't waiting for a new date.")
    fields: dict[str, Any] = {"cancelled": False, "start": start, "end": end}
    return apply_as_person(
        store, cfg, [_edit(entry, fields)], f"Gave {entry.data['title']} a new date", note=f"New date {start}"
    )


def drop(store: Any, cfg: Any, entry_id: str, reason: str) -> str:
    """The person drops a called-off entry with a reason in their words. It is closed, never counted as done or missed;
    the to-dos held for it are asked about once."""
    from engine.applier import apply_as_person

    entry = _entry(store, entry_id)
    why = " ".join((reason or "").split())
    if not why:
        raise StoreError("Say why it is dropped.")
    if not entry.data.get("cancelled"):
        raise StoreError("Only an entry that is called off can be dropped.")
    if entry.data.get("dropped"):
        raise StoreError("That entry is dropped already.")
    return apply_as_person(
        store, cfg, [_edit(entry, {"dropped": why[:500]})], f"Dropped {entry.data['title']}", note=why
    )


def keep_todos(store: Any, cfg: Any, entry_id: str) -> str:
    """Keep the to-dos held for a dropped entry: they come off hold and lose the entry's date, one change."""
    from engine.applier import apply_as_person

    entry = _entry(store, entry_id)
    view = store.read()
    todos = held_todos(view, entry_id)
    if not todos:
        raise StoreError("Nothing is held for that entry.")
    ops = [
        {
            "op": "record.edit",
            "record": {"kind": "action", "id": a.id},
            "fields": {"on_hold": None, "due_event": None, "due": None, "due_words": None, "due_check": False},
            "read_version": a.version,
        }
        for a in todos
    ]
    return apply_as_person(store, cfg, ops, f"Kept the to-dos of {entry.data['title']}")


def drop_todos(store: Any, cfg: Any, entry_id: str) -> str:
    """Drop the to-dos held for a dropped entry, with the entry's reason, one change."""
    from engine.applier import apply_as_person

    entry = _entry(store, entry_id)
    todos = held_todos(store.read(), entry_id)
    if not todos:
        raise StoreError("Nothing is held for that entry.")
    reason = str(entry.data.get("dropped") or "called off")
    ops = [{"op": "action.drop", "id": a.id, "reason": reason, "evidence": {"quote": reason}} for a in todos]
    return apply_as_person(store, cfg, ops, f"Dropped the to-dos of {entry.data['title']}", note=reason)
