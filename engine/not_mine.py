"""Not mine to track (design 6.22): the person says one item from a watched source isn't theirs to track. It is the
person's own change, applied at once with a read-back and one Undo: the item is dropped with the person's words, so are
the source's other open to-dos and questions, and the source becomes one the person only understands, so no more are
made from it. The drops are one change the applier records (each leaves its dropped signal); the stance is saved to the
source's own setting. Undo puts back the drops and the source's earlier stance together."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine import settings as config_screens
from engine import understand
from engine.applier import apply_as_person, undo
from engine.sides import word
from engine.storage import StoreError

SETTING = "watch.sources"
OPEN = {"action": ("open", "held"), "question": ("open", "sent")}


@dataclass(frozen=True)
class Done:
    changeset: str
    source: str  # the source's id
    label: str  # what the source is called on screen
    others: int  # the other open items dropped with the one asked about
    before: str  # the source's stance before
    read_back: str  # the words that say what was done


def _watch_of(store: Any, record: Any) -> str | None:
    return understand.watched_source(store.read(), record.data.get("source"))


def items_of(store: Any, watch: str) -> list[tuple[str, str]]:
    """The open to-dos and questions that came from a watched source, as (kind, id), oldest first."""
    view = store.read()
    found = []
    for kind, states in OPEN.items():
        for record in view.list(kind):
            if record.data["status"] in states and understand.watched_source(view, record.data.get("source")) == watch:
                found.append((kind, record.id))
    return found


def apply(ws: Any, store: Any, cfg: Any, kind: str, item_id: str, note: str | None = None, env: Any = None) -> Done:
    """Drop the item and the source's other open items, and set the source to understand, as the person's own change.
    Raises `StoreError` in plain words when the item isn't open or didn't come from a watched source still listed."""
    if kind not in OPEN:
        raise StoreError("Only a to-do or a question can be set aside this way.")
    record = store.read().get(kind, item_id)
    if record is None or record.data["status"] not in OPEN[kind]:
        raise StoreError("That item isn't open any more.")
    watch = _watch_of(store, record)
    source = next((s for s in cfg.watch.sources if s.id == watch), None) if watch else None
    if source is None:
        raise StoreError("That item didn't come from a source the assistant watches.")
    reason = " ".join((note or "").split()) or word(cfg, "not_mine.reason")
    chosen = [(kind, item_id), *[i for i in items_of(store, watch) if i != (kind, item_id)]]
    ops = [{"op": f"{k}.drop", "id": i, "reason": reason} for k, i in chosen]
    changeset = apply_as_person(store, cfg, ops, word(cfg, "not_mine.summary"), note=reason)
    before = source.stance
    if before != understand.UNDERSTAND:
        _save_stance(ws, cfg, store, watch, understand.UNDERSTAND, env)
    label = source.label or source.id
    others = len(chosen) - 1
    read_back = word(cfg, "not_mine.read_back").format(count=others, source=label)
    return Done(changeset, watch, label, others, before, read_back)


def undo_it(ws: Any, store: Any, cfg: Any, changeset: str, watch: str, stance: str, env: Any = None) -> int:
    """Take the drops back and put the source's stance back as it was. Returns how many drops were undone."""
    if stance not in (understand.FOLLOW, understand.UNDERSTAND):
        raise StoreError("That isn't a stance a source can have.")
    report = undo(store, changeset)
    if any(s.id == watch for s in cfg.watch.sources):
        _save_stance(ws, cfg, store, watch, stance, env)
    return len(report.restored)


def _save_stance(ws: Any, cfg: Any, store: Any, watch: str, stance: str, env: Any) -> None:
    sources = [s.model_dump(mode="json") for s in cfg.watch.sources]
    for entry in sources:
        if entry["id"] == watch:
            entry["stance"] = stance
    config_screens.save(
        ws,
        cfg,
        store,
        changes={SETTING: sources},
        reset=[],
        read_fingerprint=config_screens.fingerprint(ws.config_dir),
        env=env,
        allow=(SETTING,),
    )
