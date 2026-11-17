"""A tally of who the person deals with (design 6.22, "Learning the person from their mail and calendar"): each address
the mail sources' message headers show, with the name it is shown under, how many messages came from it and how many
the person sent to it, the first and the last day, the sides its sources serve and whether the person ever wrote to it.
Headers only, never message text, and no AI.

The tally is worked out from the snapshots the sources already keep, each time it is asked for. It is derived data: it
has no record of its own, so the export and import leave it as they are, and forgetting a person, which redacts the
snapshots that name them, reaches it. It is a plain count: it narrows what the assistant looks at and decides nothing.

The person's own addresses are left out, and so are senders the person set aside (`Contact.apart`). Nobody else is left
out. A role word, a code in the address, an automated domain, a company word in the name, bulk mail and a tracked kind
of mail are `Contact.hints`: facts about the address the assistant weighs when it reads who is a person to the person,
never a verdict (a recruiter writes from a role address, a tradesperson's name reads as a company, a person's
address may carry a tag). Reads only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from engine import people_suggestions as ps
from engine import sides
from engine.today import zone

#: Why an address is kept apart: the person set its mail aside.
SET_ASIDE = "set_aside"
#: What an address shows that the assistant may weigh, in the words the packet gives it.
AUTOMATED, ROLE, CODE, COMPANY, BULK, TRACKED = "automated", "role", "code", "company", "bulk", "tracked"
HINT_WORDS = {
    AUTOMATED: "automated sender",
    ROLE: "role address",
    CODE: "code in the address",
    COMPANY: "name has a company word",
    BULK: "marked bulk mail",
    TRACKED: "mail of a kind the app tracks",
}

#: The marks that split an address's local part into words.
_LOCAL_MARKS = re.compile(r"[._+=-]+")
_WORD = re.compile(r"[a-z]+")
#: Letters a hexadecimal code is written in.
_HEX = re.compile(r"[0-9a-f]+")
#: The shortest run of letters and digits that can be a code rather than a word or a name.
_CODE_LENGTH = 8
#: A longer run with digits scattered through it in at least this many separate places is an identifier.
_SCATTERED_LENGTH = 12
_SCATTERED_RUNS = 3
_DIGIT_RUNS = re.compile(r"\d+")


def local_has_code(local: str) -> bool:
    """Whether an address's local part (before the @ sign) holds a run that looks like a code: at least `_CODE_LENGTH`
    letters and digits with a digit that is hexadecimal or at least half digits, or a run of at least
    `_SCATTERED_LENGTH` with digits in `_SCATTERED_RUNS` or more places. A hint only: a person's own address
    may carry such a tag."""
    for word in _LOCAL_MARKS.split(local.lower()):
        digits = sum(c.isdigit() for c in word)
        if len(word) >= _CODE_LENGTH and digits and (_HEX.fullmatch(word) or digits * 2 >= len(word)):
            return True
        if len(word) >= _SCATTERED_LENGTH and len(_DIGIT_RUNS.findall(word)) >= _SCATTERED_RUNS:
            return True
    return False


def domain_is_automated(domain: str, words: set[str]) -> bool:
    """Whether the first part of an address's domain is, in a whole word of it, one of `words` (`replies` in
    `replies.example.com`)."""
    return any(w in words for w in _LOCAL_MARKS.split(domain.lower().partition(".")[0]))


def _first_word(local: str) -> str:
    found = _WORD.match(local.lower())
    return found.group(0) if found else ""


def _names_a_company(display: str, words: set[str]) -> bool:
    return any(w in words for w in _WORD.findall(display.lower()))


@dataclass(frozen=True)
class Contact:
    """One address in the tally. `name` is the shown name, or one made from the address when none is shown; `shown` is
    the shown name as the header gave it (empty when none). `from_them` counts messages that came from the address and
    `to_them` those the person sent to it. `apart` is `SET_ASIDE` when the person set its mail aside, else None.
    `hints` are the marks the address shows, in a fixed order (see `HINT_WORDS`): facts to weigh, never reasons to leave
    it out."""

    address: str
    name: str
    shown: str
    from_them: int
    to_them: int
    first: date | None
    last: date | None
    sides: tuple[str, ...] = ()
    apart: str | None = None
    hints: tuple[str, ...] = ()

    @property
    def wrote_to(self) -> bool:
        """Whether the person ever wrote to the address."""
        return self.to_them > 0

    @property
    def total(self) -> int:
        return self.from_them + self.to_them


@dataclass
class _Row:
    shown: str = ""
    name: str = ""
    from_them: int = 0
    to_them: int = 0
    first: date | None = None
    last: date | None = None
    sides: set[str] = field(default_factory=set)
    company: bool = False


def _day(value: Any, here: Any) -> date | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(here).date() if moment.tzinfo else moment.date()


def _usable(snap: Any) -> bool:
    """Whether a snapshot is a message that still counts: mail set aside or deleted counts too (its sender is kept
    apart), mail no longer in its source doesn't."""
    data = snap.data
    return bool(data.get("message")) and not data.get("gone")


def held_messages(view: Any, source_id: str) -> list[Any]:
    """The messages of a source the app holds details of: its snapshots that are messages still in the source, and the
    headers kept from its first sign-in's year (`mail_header`) for a message no snapshot stands for. A header is read
    here like a snapshot's details and is never an input."""
    found = [snap for snap in view.find("snapshot", {"source": source_id}) if _usable(snap)]
    keys = {snap.data["key"] for snap in view.find("snapshot", {"source": source_id})}
    found += [h for h in view.find("mail_header", {"source": source_id}) if h.data["key"] not in keys]
    return found


def tally(store: Any, cfg: Any) -> list[Contact]:
    """Every address the mail sources' headers show, the most dealt with first (messages each way added), then by name.
    Sent mail (a source whose author is the person) counts each address it went to; received mail counts its sender."""
    settings = cfg.ui.walkthrough
    sources = ps._mail_sources(store, cfg)
    person = cfg.workspace.user.person
    sent_ids = {s.id for s in sources if person and s.author == person}
    own = ps._own_addresses(store, cfg, sources)
    automated = tuple(w.lower() for w in cfg.watch.automated_mail.senders)
    roles = {w.strip().lower() for w in settings.not_people_addresses if w.strip()}
    companies = {w.strip().lower() for w in settings.not_people_names if w.strip()}
    domain_words = {w.strip().lower() for w in settings.not_people_domain_words if w.strip()}
    set_aside, set_aside_domains = ps._set_aside(store, cfg, sources)
    bulk, tracked = ps._mail_marks(store, cfg, sources)
    view = store.read()
    here = zone(cfg)
    rows: dict[str, _Row] = defaultdict(_Row)

    def note(entries: list[str], source: Any, snap: Any, *, sent: bool) -> None:
        seen: set[str] = set()
        served = sides.watch_source_sides(view, cfg, source.id)
        when = _day((snap.data.get("message") or {}).get("received"), here) or _day(snap.data.get("seen_at"), here)
        for entry in entries:
            display, address = ps._parsed(entry)
            display = re.sub(r"\s+", " ", display.replace('"', "")).strip()
            if not address or address in seen or address in own:
                continue
            seen.add(address)
            row = rows[address]
            if display and "@" not in display and not row.shown:
                row.shown = display
            row.name = row.name or ps._name_of(display, address)
            if sent:
                row.to_them += 1
            else:
                row.from_them += 1
            if display and _names_a_company(display, companies):
                row.company = True
            if when is not None:
                row.first = when if row.first is None else min(row.first, when)
                row.last = when if row.last is None else max(row.last, when)
            row.sides.update(served)

    for s in sources:
        sent = s.id in sent_ids
        for snap in held_messages(view, s.id):
            message = snap.data["message"]
            if sent:
                note(list(message.get("participants") or []), s, snap, sent=True)
            elif message.get("sender"):
                note([message["sender"]], s, snap, sent=False)

    found = []
    for address, row in rows.items():
        local, _, domain = address.partition("@")
        apart = SET_ASIDE if address in set_aside or domain in set_aside_domains else None
        marks = (
            (AUTOMATED, local.startswith(automated) or domain_is_automated(domain, domain_words)),
            (ROLE, _first_word(local) in roles),
            (CODE, local_has_code(local)),
            (COMPANY, row.company),
            (BULK, address in bulk),
            (TRACKED, address in tracked),
        )
        found.append(
            Contact(
                address,
                row.name,
                row.shown,
                row.from_them,
                row.to_them,
                row.first,
                row.last,
                tuple(sorted(row.sides)),
                apart,
                tuple(name for name, shown in marks if shown),
            )
        )
    found.sort(key=lambda c: (-c.total, c.name.lower(), c.address))
    return found
