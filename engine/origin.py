"""Where an item came from (design 7.5): the one place that decides what a "where it came from" link opens.

In order of what exists: the original page, when the input the item came from has an address a browser can open; else
the saved text of that input; else the change that created the item, with the request behind it. An item is made from
an input by its `source`; a piece of knowledge names it in its evidence. An item none of those
reach (made by the engine itself, or imported without its history) has no origin, and the screen shows no link. A to-do
the person typed themselves has none either: there is nothing to go back to but their own typing.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from engine.knowledge import KINDS as KNOWLEDGE_KINDS
from engine.untrusted import neutralize

LINK, SOURCE, CHANGE = "link", "source", "change"
#: The op a request made by the person's own act on screen is written with (`apply_as_person`).
SCREEN_REQUEST_OP = "screen.request"


def _openable(url: object) -> bool:
    """Whether an address is a web page a person can open: a web scheme and a host."""
    if not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _source_id(kind: str, data: dict[str, Any]) -> str | None:
    """The input a record was made from: its own `source`; for a piece of knowledge, the one its evidence cites."""
    if kind in KNOWLEDGE_KINDS:
        return (data.get("evidence") or {}).get("source") or None
    return data.get("source") or None


def source_origin(source: Any) -> dict[str, Any] | None:
    """The origin an input itself gives: its original page when it has an address a browser can open, else its saved
    text; None for no input. `watch` names the watched source that handed the input in, when one did (the row's
    "Not mine to track" is offered by it)."""
    if source is None:
        return None
    watched = source.data.get("watched")
    watch = watched.get("source") if isinstance(watched, dict) else None
    extra = {"watch": watch} if watch else {}
    if _openable(source.data.get("url")):
        return {"kind": LINK, "url": source.data["url"].strip(), "source": source.id, **extra}
    return {"kind": SOURCE, "source": source.id, **extra}


def origins(view: Any, kind: str, ids: Iterable[str]) -> dict[str, dict[str, Any] | None]:
    """The origin of each record of `kind` named in `ids`, by id: a dict with `kind` (link, source or change) and the
    address, source, change and request it needs, or None. Reads only."""
    wanted = list(ids)
    if not wanted:
        return {}
    created: dict[str, tuple[str | None, str | None]] | None = None
    typed: dict[str, tuple[str, str]] = view.creators(kind) if kind == "action" else {}
    out: dict[str, dict[str, Any] | None] = {}
    for record_id in wanted:
        record = view.get(kind, record_id, include_deleted=True)
        source_id = _source_id(kind, record.data) if record is not None else None
        source = view.get("source", source_id) if source_id else None
        found = source_origin(source)
        if found is not None:
            out[record_id] = found
            continue
        if typed.get(record_id, ("", ""))[0] == "pm":
            out[record_id] = None
            continue
        if created is None:
            created = view.creations(kind)
        changeset, request = created.get(record_id, (None, None))
        if request and _made_on_screen(view, request):
            out[record_id] = None  # the person typed it: there is no input or request behind it to open
        elif changeset and view.get("changeset", changeset) is not None:
            out[record_id] = {"kind": CHANGE, "changeset": changeset, "request": request}
        else:
            out[record_id] = None
    return out


def _made_on_screen(view: Any, request_id: str) -> bool:
    """Whether a request was made by the person's own act on screen (a to-do typed, a form saved), which has no input
    and no work behind it: the ledger names the screen as the one that wrote it."""
    first = view.ledger(kind="request", record_id=request_id)
    return bool(first) and first[0].get("op") == SCREEN_REQUEST_OP


def from_outside(view: Any, record: Any, kind: str | None = None) -> bool:
    """Whether a record was made from an input that was not the person's own words (a mail, a page): what it holds, an
    address to open or a sum to pay, is outside content, and the step that acts on it says so. A record with no input is
    not from outside."""
    source_id = _source_id(kind or record.kind, record.data)
    source = view.get("source", source_id) if source_id else None
    return source is not None and source.data.get("trust") != "trusted"


def name_from_outside(view: Any, record: Any) -> bool:
    """Whether the name of a person or project (and the other names it goes by) was read from an input that wasn't the
    person's own words: the record was made by work on a mail or page, and the person has neither made it nor
    confirmed it. A record the person made or confirmed, or one with no work behind it, is not from outside."""
    if record.data.get("name_verified"):
        return False
    made = view.creations(record.kind).get(record.id)
    if made is None or not made[1]:
        return False
    if view.creators(record.kind).get(record.id, ("", ""))[0] == "pm":
        return False
    request = view.get("request", made[1])
    return request is not None and from_outside(view, request)


def marked_words(record_id: str, words: str) -> str:
    """Words read from outside, fenced as outside content (neutralized, with the record they belong to)."""
    return f'<untrusted source="{record_id}">{neutralize(words)}</untrusted>'


def marked_name(view: Any, record: Any, words: str) -> str:
    """A name of a person or project (or an alias or role of one) as text a model reads: marked as outside content when
    `name_from_outside` holds, so a name can't carry an instruction. The person's own and confirmed names are as they
    are. The one place the rule for writing a name into model-read text lives."""
    return marked_words(record.id, words) if name_from_outside(view, record) else words
