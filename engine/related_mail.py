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

#: A code a booking or an order carries: letters and digits together, six or more long. It is matched on the text in
#: upper case, so a code written in lower case is the same code. A number alone (a phone number, a date, an amount) is
#: never one.
_REFERENCE = re.compile(r"\b(?=[A-Z0-9-]{6,}\b)(?=[A-Z-]*\d)(?=[0-9-]*[A-Z])[A-Z0-9-]+\b")
#: Letters and digits that aren't a code: a word with a small number after it ("COVID19", "COVID-19"), a year's quarter
#: or half, or a fiscal year ("2026-Q4", "Q4-2026", "H1-2026", "FY2026").
_NOT_A_CODE = re.compile(r"[A-Z]{4,}-?\d{1,2}|(?:19|20)\d\d-?[QH][1-4]|[QH][1-4]-?(?:19|20)\d\d|FY-?(?:19|20)?\d\d")


def references_in(text: str, language: Any = None) -> set[str]:
    """The booking or order codes in the text: letters and digits together, or digits alone right after a word that
    names a code ("confirmation 48213977", "Order #: 48213977"). Never a phone number or a date, a year's quarter or
    half, a word with a number after it, or a label or an amount with its number ("ROOM101", "USD1500": the language
    settings' `code_label_words`). `language` is the language settings; the shipped lists when none is given."""
    from engine.language_words import language_words, shipped

    def words(name: str) -> list[str]:
        found = language_words(language, name) if language is not None else shipped(name)
        return [str(w).upper() for w in found or []]

    labels = words("code_label_words")
    upper = (text or "").upper()
    found = {code.strip("-") for code in _REFERENCE.findall(upper)}
    codes = {
        code
        for code in found
        if len(code) >= 6
        and not _NOT_A_CODE.fullmatch(code)
        and not any(re.fullmatch(re.escape(label) + r"-?\d{1,6}", code) for label in labels)
    }
    leads = words("code_lead_words")
    if leads:
        lead = "|".join(re.escape(w) for w in sorted(leads, key=len, reverse=True))
        codes |= set(
            re.findall(
                rf"\b(?:{lead})\b(?:[^0-9A-Z\n]{{0,4}}(?:NUMBER|NO\.?|CODE|ID|IS)\b){{0,2}}[^0-9A-Z\n]{{0,4}}(\d{{6,}})\b",
                upper,
            )
        )
    return codes


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
    codes = references_in(f"{this.data.get('title') if this is not None else ''}\n{text}", cfg.language)
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
        shared = bool(codes) and bool(
            codes & references_in(f"{snap.data.get('title') or ''}\n{body_text}", cfg.language)
        )
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
