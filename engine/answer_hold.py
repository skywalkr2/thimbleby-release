"""An answer that puts a question off to a later day holds that question to that day (design 6.8, 6.32).

When the person answers a question put to them "let's follow up on this in 2 days", the words say when to come back to
it, not what the answer is. The same question waits until that working day: it leaves Today and the decisions list, is
not chased, shows when it comes back where it is listed, and is there again on that day. Nothing is closed, no note goes
to the assistant, and so no second to-do is made for the same thing.

A plain function only reads the words: a word of the language settings' `answer_later_words`, as whole words, and a day
the date reader (`engine/due_phrases.py`) reads after it, ahead of today on the person's own clock: a weekday or date,
a span ("in 2 days") or the day of the meeting named after "after". Words with no such day change nothing and are
handled as any answer is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from engine.due_phrases import after_marker, date_phrases, load_holidays, named_entry, resolve
from engine.language_words import language_words
from engine.names import People
from engine.storage import Store, StoreError
from engine.today import zone

#: Questions whose answer is itself the change, or that are answered where the item waits: never put off by words.
NOT_PUT_OFF = ("owner", "held-op", "away", "routing", "watch")
_EDGE = ',.;:!?"“”()'


@dataclass(frozen=True)
class Hold:
    """What the answer put the question off to: the hold as the question keeps it, and the day it comes back."""

    held_for: dict[str, str]
    day: date


def _reader(cfg: Any, today: date) -> Any:
    language = (cfg.workspace.language or "en-US").replace("_", "-")
    settings = cfg.language
    where = zone(cfg)
    received = datetime(today.year, today.month, today.day, 12, tzinfo=where)

    def read(phrase: str) -> date | None:
        found = resolve(
            phrase,
            received,
            where,
            locale="en_US" if language.lower().startswith("en-us") else "en_GB",
            lead_words=language_words(settings, "due_lead_words"),
            before_words=language_words(settings, "due_before_words"),
            span_words=language_words(settings, "due_span_words"),
            ordinal_suffixes=language_words(settings, "due_ordinal_suffixes"),
            phrase_words=language_words(settings, "due_phrase_words"),
            number_words=language_words(settings, "due_number_words"),
            time_zones=language_words(settings, "time_zone_abbreviations"),
            sender_zone=where,
            holidays=load_holidays(settings.holiday_calendar or language),
        )
        return found.end or found.start

    return read


def _day_in(words: str, read: Any) -> date | None:
    """The first day the words name, reading windows of up to four words from the start of the words on."""
    tokens = words.split()
    for i in range(len(tokens)):
        for size in range(4, 0, -1):
            phrase = " ".join(tokens[i : i + size]).strip(_EDGE)
            if phrase and (day := read(phrase)) is not None:
                return day
    return None


def read(view: Any, cfg: Any, text: str, today: date) -> Hold | None:
    """The hold the words ask for, or None when they name no later day to come back on (or are not in a language the
    date reader knows)."""
    language = (cfg.workspace.language or "en-US").replace("_", "-")
    if not language.lower().startswith("en"):
        return None
    settings = cfg.language
    tail = after_marker(text, language_words(settings, "answer_later_words"))
    if tail is None:
        return None
    reader = _reader(cfg, today)
    # "after Thursday's meeting": the day of that meeting, as the entry itself when the words name one.
    meeting = after_marker(tail, language_words(settings, "due_hold_words"))
    if meeting:
        entry = named_entry(view.list("event"), meeting, today.isoformat())
        if entry is not None and (day := date.fromisoformat(str(entry.data["start"])[:10])) > today:
            return Hold({"event": entry.id}, day)
        for phrase in date_phrases(meeting):
            if (day := reader(phrase)) is not None and day > today:
                return Hold({"on": day.isoformat()}, day)
        return None
    day = _day_in(tail, reader)
    if day is None or day <= today:
        return None
    return Hold({"on": day.isoformat()}, day)


def asks_for_hold(store: Store, cfg: Any, question_id: str, text: str | None, today: date) -> Hold | None:
    """The hold the person's words ask for on this question, or None when it is not one they can put off: an open
    question to them (not about who, a held op or a routing) with no hold that already reaches that day."""
    if not (text or "").strip():
        return None
    view = store.read()
    question = view.get("question", question_id)
    if question is None:
        return None
    d = question.data
    if d.get("status") != "open" or d.get("to") != People(store, cfg).pm:
        return None
    if (d.get("resolves") or {}).get("kind") in NOT_PUT_OFF:
        return None
    return read(view, cfg, " ".join(text.split()), today)


def hold(store: Store, cfg: Any, question_id: str, text: str | None, today: date | None = None) -> Hold | None:
    """Hold the question when the person's words put it off to a later day, as their own change. Returns the hold, or
    None when the words ask for none (nothing is changed). The question stays open, so a hold taken back or ended
    brings it to Today as any open question."""
    from engine.followups import FollowUpError, hold_question

    today = today or datetime.fromisoformat(store.clock()).astimezone(zone(cfg)).date()
    found = asks_for_hold(store, cfg, question_id, text, today)
    if found is None:
        return None
    try:
        hold_question(store, question_id, found.held_for, today=today, here=zone(cfg))
    except FollowUpError as err:
        raise StoreError(str(err)) from None
    return found


def is_put_off(view: Any, data: dict[str, Any], today: date, here: Any) -> bool:
    """Whether an open question is held to a day after today, so Today, the decisions list and the week leave it out
    until then."""
    from engine.followups import held_until_day

    if not data.get("held_for") or data.get("status") != "open":
        return False
    until, _ = held_until_day(view, data["held_for"], today, here)
    return until is not None and until > today
