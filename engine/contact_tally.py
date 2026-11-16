"""A tally of who the person deals with (design 6.22, "Learning the person from their mail and calendar"): each address
the mail sources' message headers show, with the name it is shown under, how many messages came from it and how many
the person sent to it, the first and the last day, the sides its sources serve and whether the person ever wrote to it.
Headers only, never message text, and no AI.

The tally is worked out from the snapshots the sources already keep, each time it is asked for. It is derived data: it
has no record of its own, so the export and import leave it as they are, and forgetting a person, which redacts the
snapshots that name them, reaches it. It is a plain count: it narrows what the assistant looks at and decides nothing.

Machine-made and bulk addresses stay in the tally, kept apart (`Contact.apart` says why), by the same tests the People
step uses (`engine.people_suggestions`): the person themselves, role and company addresses, codes, automated domains,
and senders whose mail is bulk, set aside or of a tracked kind. The person's own addresses are left out altogether.
Reads only.
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

#: Why an address is kept apart.
SET_ASIDE, AUTOMATED, ROLE, CODE, COMPANY = "set_aside", "automated", "role", "code", "company"


@dataclass(frozen=True)
class Contact:
    """One address in the tally. `name` is the shown name, or one made from the address when none is shown; `shown` is
    the shown name as the header gave it (empty when none). `from_them` counts messages that came from the address and
    `to_them` those the person sent to it. `from_them_named` counts the received ones whose shown name has a person's
    form. `apart` is why the address is kept apart (a machine, a list, a company or a role), or None."""

    address: str
    name: str
    shown: str
    from_them: int
    to_them: int
    from_them_named: int
    first: date | None
    last: date | None
    sides: tuple[str, ...] = ()
    apart: str | None = None

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
    named: int = 0
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
    blocked_addresses, blocked_domains = ps._blocked(store, cfg, sources)
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
                if display and "@" not in display and ps._looks_like_a_person(display):
                    row.named += 1
            if display and ps._names_a_company(display, companies):
                row.company = True
            if when is not None:
                row.first = when if row.first is None else min(row.first, when)
                row.last = when if row.last is None else max(row.last, when)
            row.sides.update(served)

    for s in sources:
        sent = s.id in sent_ids
        for snap in view.find("snapshot", {"source": s.id}):
            if not _usable(snap):
                continue
            message = snap.data["message"]
            if sent:
                note(list(message.get("participants") or []), s, snap, sent=True)
            elif message.get("sender"):
                note([message["sender"]], s, snap, sent=False)

    found = []
    for address, row in rows.items():
        local, _, domain = address.partition("@")
        apart: str | None = None
        if address in blocked_addresses or domain in blocked_domains:
            apart = SET_ASIDE
        elif local.startswith(automated) or ps.domain_is_automated(domain, domain_words):
            apart = AUTOMATED
        elif ps._first_word(local) in roles:
            apart = ROLE
        elif ps.local_is_code(local):
            apart = CODE
        elif row.company:
            apart = COMPANY
        found.append(
            Contact(
                address,
                row.name,
                row.shown,
                row.from_them,
                row.to_them,
                row.named,
                row.first,
                row.last,
                tuple(sorted(row.sides)),
                apart,
            )
        )
    found.sort(key=lambda c: (-c.total, c.name.lower(), c.address))
    return found
