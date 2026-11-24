"""Later mail about the same booking, shown to a run on mail the person deleted (design 6.32). A confirmation of a
booking, an appointment or a delivery in deleted mail is often deleted because it was called off, and the
cancellation is a separate message in any folder. Whether a later message cancels the booking is the assistant's
judgment; this only narrows what it is shown: the mail from the same sender address, or naming a reference (a
booking or order code) that both messages hold. The messages are outside data, never instructions."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from engine.config import Config
from engine.intake import source_text
from engine.set_aside import address_of
from engine.storage import Store, Stored
from engine.triage import sender_address
from engine.untrusted import outside_block, quoted_attribute
from engine.workspace import Workspace

#: A code a booking or an order carries: letters and digits together, or a long number, six or more long. It is
#: matched on the text in upper case, so a code written in lower case is the same code.
_REFERENCE = re.compile(r"\b(?=[A-Z0-9-]{6,}\b)(?:(?=[A-Z-]*\d)(?=[0-9-]*[A-Z])[A-Z0-9-]+|\d{7,})\b")


def references_in(text: str) -> set[str]:
    """The booking or order codes in the text (a date such as 2026-11-19 is not one)."""
    return {code.strip("-") for code in _REFERENCE.findall((text or "").upper()) if len(code.strip("-")) >= 6}


def _moment(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def related(ws: Workspace, store: Store, cfg: Config, saved: Stored | None) -> list[tuple[Stored, str]]:
    """The mail snapshots (any folder) that arrived after the watched message `saved` and come from its sender
    address or name a reference it holds, newest first, each with its saved text; at most the configured number."""
    if saved is None:
        return []
    view = store.read()
    watched = saved.data.get("watched") or {}
    this = (
        next(iter(view.find("snapshot", {"source": watched["source"], "key": watched["key"]})), None)
        if watched
        else None
    )
    text = source_text(ws, store, saved.id)
    sender = address_of(this, ws) if this is not None else sender_address({"now": text[:1000]})
    codes = references_in(f"{this.data.get('title') if this is not None else ''}\n{text}")
    own = ((this.data.get("message") or {}).get("received")) if this is not None else None
    since = _moment(own or saved.data.get("received_at"))
    found: list[tuple[datetime, Stored, str]] = []
    for snap in view.list("snapshot"):
        if (
            (this is not None and snap.id == this.id)
            or not snap.data.get("message")
            or snap.data.get("deleted")
            or snap.data.get("gone")
        ):
            continue
        when = _moment(snap.data["message"].get("received") or snap.data.get("seen_at"))
        if since is not None and when is not None and when <= since:
            continue
        body = ws.sources_dir / f"{snap.data['content_hash']}.txt"
        body_text = body.read_text(encoding="utf-8") if body.exists() else ""
        if not body_text:
            continue
        same_sender = bool(sender) and address_of(snap, ws) == sender
        shared = bool(codes) and bool(codes & references_in(f"{snap.data.get('title') or ''}\n{body_text}"))
        if same_sender or shared:
            found.append((when or datetime.min.replace(tzinfo=UTC), snap, body_text))
    found.sort(key=lambda row: row[0], reverse=True)
    return [(snap, body) for _when, snap, body in found[: cfg.dispatch.knowledge.related_mail_items]]


def packet_section(ws: Workspace, store: Store, cfg: Config, saved: Stored | None) -> str:
    """The related messages as outside blocks, each with its subject, sender, date, folder and first lines; empty
    when none is related or the setting is 0."""
    if cfg.dispatch.knowledge.related_mail_items <= 0:
        return ""
    blocks = []
    for snap, body in related(ws, store, cfg, saved):
        message = snap.data["message"]
        marks = f' folder="{quoted_attribute(message.get("where") or "inbox")}"'
        if message.get("received"):
            marks += f' received="{quoted_attribute(message["received"])}"'
        if message.get("sender"):
            marks += f' from="{quoted_attribute(message["sender"])}"'
        marks += f' subject="{quoted_attribute(snap.data.get("title") or "")[:200]}"'
        blocks.append(
            outside_block(body[: cfg.dispatch.knowledge.related_mail_chars], snap.data["source"], marks=marks)
        )
    if not blocks:
        return ""
    head = (
        "Later mail, in any folder, from the same sender or naming the same reference as this message. Read it to "
        "see whether it called off the booking, appointment or delivery this message confirms:"
    )
    return head + "\n\n" + "\n\n".join(blocks)
