"""Where a calendar entry came from, for the one op that calls an entry off on the assistant's word (`event.cancel`).

The assistant may call off only an entry it made from a mail message: never the person's own entry (typed, made from
a screen, a reminder, one that repeats), never one a connected calendar holds (the calendar says so itself), and never
one the person has changed since. The check reads the records, never the entry's words, and is an invariant.
"""

from __future__ import annotations

from typing import Any


def not_from_mail_problem(view: Any, entry: Any) -> str | None:
    """Why the assistant may not call this entry off, or None when it was made from a mail message and no one has
    changed it. The reason is plain words for the assistant's return round."""
    data = entry.data
    if data.get("key"):
        return "a connected calendar holds this entry, and the calendar says itself when it is called off"
    if data.get("reminder") or data.get("repeat") or data.get("role") or data.get("dropped"):
        return "this is the person's own entry, so only they call it off"
    source = view.get("source", data["source"]) if data.get("source") else None
    if source is None or not str(source.data.get("kind", "")).startswith("watched:") or not source.data.get("sent_at"):
        return "this entry was not made from a mail message, so only the person calls it off"
    if (source.data.get("watched") or {}).get("by_you"):
        return "this entry was made from mail the person wrote, so only they call it off"
    if data.get("trust") != "untrusted" or not data.get("evidence"):
        return "this entry is the person's own, so only they call it off"
    if any(row["actor"] == "pm" for row in view.ledger(kind="event", record_id=entry.id)):
        return "the person has changed this entry, so only they call it off"
    return None


#: What the person is asked when a mail that calls an entry off is from another sender than the mail that made it.
OTHER_SENDER_ASKS = "A mail says your {title} for {day} is canceled, but it's from a different sender: call it off?"
#: What the person is asked when the sender is the same but the mail doesn't show it is that booking.
UNCLEAR_ASKS = (
    "A mail from the same sender may cancel your {title} for {day}, but it doesn't say which booking: call it off?"
)
#: What the person is asked when the sender of either mail can't be told from the records.
UNKNOWN_SENDER_ASKS = "A message says your {title} for {day} is canceled, but it doesn't show who sent it: call it off?"
#: Why a cancellation naming another reference changes nothing.
OTHER_REFERENCE = (
    "the cancellation names a different booking reference than the entry's mail does, so it is not this booking"
)

_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def _domain(address: str) -> str:
    return address.rpartition("@")[2].strip().lower() if "@" in address else ""


def _names_day(text: str, day: Any) -> bool:
    """Whether the text names this date: as an ISO date, a month name and day in either order, or numbers."""
    import re

    month = _MONTHS[day.month - 1]
    words = f"(?:{month}|{month[:3]}\\.?)"
    number = rf"(?<!\d){day.day}(?:st|nd|rd|th)?(?!\d)"
    patterns = [
        re.escape(day.isoformat()),
        rf"\b{words}\s+{number}",
        rf"{number}\s+(?:of\s+)?{words}\b",
        rf"(?<!\d){day.month}/{day.day}(?:/(?:{day.year}|{day.year % 100:02d}))?(?!\d)",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _names_place(text: str, place: Any) -> bool:
    """Whether the text names the entry's place, ignoring case and the spacing between words. False for an entry with
    no place."""
    wanted = " ".join(str(place or "").casefold().split())
    return bool(wanted) and wanted in " ".join(text.casefold().split())


def _mail_sender(store: Any, view: Any, ws: Any, source_id: str | None, head: str) -> str:
    """The sender address of the mail a source holds, from the mail service's own record of it (its snapshot); empty
    when there is none. Never from a From line in the text: anyone can write one, and a cancellation is exactly what
    a spoofed mail would fake, so a mail with no such record counts as an unknown sender and asks."""
    from engine.set_aside import address_of

    source = view.get("source", source_id) if source_id else None
    watched = (source.data.get("watched") if source is not None else None) or {}
    if watched:
        snap = next(iter(view.find("snapshot", {"source": watched.get("source"), "key": watched.get("key")})), None)
        if snap is not None and (found := address_of(snap, ws)):
            return found
    return ""


def cancel_match(view: Any, ctx: Any, entry: Any, quote: str, day: Any) -> tuple[str, str] | None:
    """Whether the mail that cancels an entry may call it off on its own, decided from the records and the two mails'
    own data, never from the words of the cancellation alone. None: it may. ("refuse", why): it names a different
    reference than the entry's mail, so it is not this booking. ("ask", question): the person decides, because the
    sender differs, can't be told, or the mail doesn't show it is that booking. A call-off applies at once only
    when the sender has the same domain as the sender of the mail that made the entry AND either the two mails share
    a reference, or the cancellation names both the entry's date and its place (an entry with no place needs the
    reference); a date alone asks."""
    from engine.intake import source_text
    from engine.related_mail import references_in
    from engine.workspace import Workspace

    store = ctx.store
    ws = Workspace(store.path.parent)
    made = view.get("source", entry.data["source"]) if entry.data.get("source") else None
    raw = ctx.inputs.raw_input or (source_text(ws, store, ctx.inputs.source) if ctx.inputs.source else "")
    cancelling = view.get("source", ctx.inputs.source) if ctx.inputs.source else None
    cancel_text = "\n".join([str(cancelling.data.get("title") or "") if cancelling else "", raw, quote])
    booking_text = "\n".join(
        [
            str(entry.data.get("title") or ""),
            str((entry.data.get("evidence") or {}).get("quote") or ""),
            str(made.data.get("title") or "") if made else "",
            source_text(ws, store, made.id) if made else "",
        ]
    )
    wanted, shown = references_in(booking_text), references_in(cancel_text)
    if wanted and shown and not (wanted & shown):
        return "refuse", OTHER_REFERENCE
    mine = _domain(_mail_sender(store, view, ws, made.id if made else None, ""))
    theirs = _domain(_mail_sender(store, view, ws, ctx.inputs.source, raw[:1000]))
    shown_day = day.strftime("%a %b ") + str(day.day)
    words = {"title": " ".join(str(entry.data["title"]).split()), "day": shown_day}
    if not mine or not theirs:
        return "ask", UNKNOWN_SENDER_ASKS.format(**words)
    if mine != theirs:
        return "ask", OTHER_SENDER_ASKS.format(**words)
    if (wanted & shown) or (_names_day(cancel_text, day) and _names_place(cancel_text, entry.data.get("where"))):
        return None
    return "ask", UNCLEAR_ASKS.format(**words)
