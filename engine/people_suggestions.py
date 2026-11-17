"""What the walkthrough's people step needs from the mail the sources already read, and its typed and pasted lists
(design 7.8). Who the person writes to is read from the contact tally (`engine.contact_tally`) and who is a person to
them is the assistant's reading (`engine.person_look`, offers the step shows); nothing here decides it. This module
holds what the tally and the step share: the mail sources, the person's own addresses, the people already on file, and
the senders the person set aside, and reads a typed or pasted list of names. Reads only: adding someone is the People
route's own add.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any

from engine.connectors import CORE, declared_reads, reads
from engine.contacts import all_values


def _name_of(display: str, address: str) -> str:
    """The name a mail header shows for someone, else one made from the words of the address before the @."""
    shown = re.sub(r"\s+", " ", display.replace('"', "")).strip()
    if shown and "@" not in shown:
        return shown
    return " ".join(w.capitalize() for w in re.split(r"[._+-]+", address.split("@", 1)[0]) if w)


def _mail_sources(store: Any, cfg: Any) -> list[Any]:
    said = declared_reads({**CORE, **store.plugins.connectors()})
    return [s for s in cfg.watch.sources if s.enabled and "mail" in (reads(s.connector, said) or [])]


def _own_addresses(store: Any, cfg: Any, sources: list[Any]) -> set[str]:
    """The addresses that are the person's own: those on their record and the accounts the mail sources read as."""
    own: set[str] = set()
    person = cfg.workspace.user.person
    record = store.read().get("person", person) if person else None
    own.update(v.lower() for v in (all_values(record.data.get("how_to_reach")) if record else []))
    for s in sources:
        for value in (s.account, s.settings.get("user")):
            if value:
                own.add(str(value).lower())
    return own


def _known(store: Any) -> tuple[set[str], set[str]]:
    """The addresses and the names (full names and aliases, lower case) of the people already on file."""
    addresses: set[str] = set()
    names: set[str] = set()
    for p in store.read().list("person"):
        addresses.update(v.lower() for v in all_values(p.data.get("how_to_reach")))
        names.update(n.lower() for n in [p.data["full_name"], *p.data.get("aliases", [])] if n)
    return addresses, names


_PERSON_WORD = re.compile(r"^[^\W\d_][^\W\d_'\u2019.-]*(?:['\u2019.-][^\W\d_]+)*\.?$")


def _parsed(entry: str) -> tuple[str, str]:
    """The shown name and the lower-case address of one header entry; the address is empty when it holds none."""
    found = getaddresses([entry])
    display, address = found[0] if found else ("", "")
    address = address.strip().lower()
    return display, address if "@" in address else ""


def _set_aside(store: Any, cfg: Any, sources: list[Any]) -> tuple[set[str], set[str]]:
    """The addresses and domains the person set aside: the senders and domains of their own set-aside rules, and the
    senders of mail they set aside or deleted. Nothing else is left out of the tally for its kind."""
    addresses: set[str] = set()
    domains: set[str] = set()
    for rule in cfg.watch.triage:
        if rule.kind == "sender-rule" and rule.set_aside in ("sales", "notices"):
            addresses.update(str(a).strip().lower() for a in rule.params.get("senders") or [])
            domains.update(str(d).strip().lower().removeprefix("@") for d in rule.params.get("domains") or [])
    view = store.read()
    for s in sources:
        for snap in view.find("snapshot", {"source": s.id}):
            message = snap.data.get("message") or {}
            _, sender = _parsed(str(message.get("sender") or ""))
            if sender and (snap.data.get("set_aside") or snap.data.get("deleted")):
                addresses.add(sender)
    return addresses, domains


def _mail_marks(store: Any, cfg: Any, sources: list[Any]) -> tuple[set[str], set[str]]:
    """The addresses whose mail the service marks bulk and those whose mail is of a kind the app tracks (a bill, an
    order, a delivery): hints for the assistant's reading, never reasons to leave anyone out."""
    from engine.mail_kinds import kind_of

    bulk: set[str] = set()
    tracked: set[str] = set()
    view = store.read()
    for s in sources:
        for snap in view.find("snapshot", {"source": s.id}):
            message = snap.data.get("message") or {}
            _, sender = _parsed(str(message.get("sender") or ""))
            if not sender:
                continue
            if message.get("bulk"):
                bulk.add(sender)
            if kind_of(cfg.watch.mail_kinds, sender, str(snap.data.get("title") or ""), ""):
                tracked.add(sender)
    return bulk, tracked


#: The most names one pasted list adds.
_PASTE_LIMIT = 200
#: The longest relation or part a pasted line may give after the name.
_RELATION_LIMIT = 60
#: A name followed by an address in angle brackets, then optionally how they relate (after a comma, semicolon or dash).
_ANGLE_FORM = re.compile(
    r"^(?P<name>[^<>]*?)\s*<(?P<address>[^<>@\s]+@[^<>@\s]+)>\s*(?:[,;]|\s[-\u2013\u2014]\s)?\s*(?P<relation>.*)$"
)
#: The mark between a name and how they relate: a comma, a semicolon, or a spaced dash.
_RELATION_MARK = re.compile(r"\s*(?:[,;]|\s[-\u2013\u2014]\s)\s*")
_BARE_ADDRESS = re.compile(r"^[^\s@<>,;]+@[^\s@<>,;]+$")


#: The most words a person's name is read as: a long real name is a name, not a line to drop.
_NAME_WORDS_MOST = 8


def reads_as_a_person(name: str, company_words: frozenset[str] = frozenset(), *, full: bool = True) -> bool:
    """Whether typed words read as a person's name: a first and a last name (two to eight words, or one when `full` is
    false) made of letters (a hyphen, apostrophe or full stop inside is fine). Numbers, marks, web addresses, a line in
    capitals only and a line holding a word that names a company (`company_words`, lower case) don't. The one rule for a
    name typed or pasted into a list."""
    parts = name.split()
    if not (1 <= len(parts) <= _NAME_WORDS_MOST) or (full and len(parts) < 2):
        return False
    if not all(_PERSON_WORD.match(w) for w in parts):
        return False
    if any(w.lower().strip(".") in company_words for w in parts):
        return False
    return not (len(parts) > 1 and all(w.isupper() and len(w) > 1 for w in parts))


@dataclass(frozen=True)
class Pasted:
    """One line of a pasted list: the `name`, the `address` when the line gave one, and how they relate (or their part)
    when it said."""

    name: str
    address: str | None = None
    relation: str | None = None


@dataclass(frozen=True)
class PastedList:
    """What a pasted list holds: the people it reads as, and the lines left out because they don't read as a person."""

    people: list[Pasted]
    left_out: list[str]


def _relation_of(words: str) -> str | None:
    said = re.sub(r"\s+", " ", words).strip().strip(",;").strip()
    return said[:_RELATION_LIMIT].strip() if re.search(r"[^\W\d_]", said) else None


def _pasted_line(line: str, company_words: frozenset[str] = frozenset()) -> Pasted | None:
    """The person one cleaned line reads as, or None when it doesn't read as one."""
    angled = _ANGLE_FORM.match(line)
    if angled:
        display, address, rest = angled["name"], angled["address"].strip().lower(), angled["relation"]
    else:
        head, rest = (_RELATION_MARK.split(line, maxsplit=1) + [""])[:2]
        head = head.strip()
        display, address = ("", head.lower()) if _BARE_ADDRESS.match(head) else (head, "")
    name = _name_of(display.replace('"', ""), address) if address else display
    name = re.sub(r"\s+", " ", name).strip()
    # A line that gives an address is known by it, so its name may be one word; a typed name is a first and a last.
    if not reads_as_a_person(name, company_words, full=not address):
        return None
    return Pasted(name, address or None, _relation_of(rest))


def parse_list(text: str, company_words: frozenset[str] = frozenset()) -> PastedList:
    """The people in a pasted list, one per line: a name, `Name <address>` or a bare address (the name its words make),
    each optionally followed by how they relate (`Name, my sister`, `Name - my sister`, `Name; my sister`). Any list
    mark (a dash, bullet or number) is dropped. A line that doesn't read as a person (numbers, marks, a web address) is
    left out and listed. Blank lines and repeats of a name or an address (ignoring capitals) are merged; at most
    `_PASTE_LIMIT` people."""
    found: list[Pasted] = []
    left_out: list[str] = []
    seen: dict[str, int] = {}  # a name or address (lower case) -> where its person is in `found`
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", raw).strip().rstrip(",;").strip()
        if not line:
            continue
        person = _pasted_line(line, company_words)
        if person is None:
            left_out.append(re.sub(r"\s+", " ", line))
            continue
        keys = {person.name.lower(), *([person.address] if person.address else [])}
        earlier = next((k for k in keys if k in seen), None)
        if earlier is not None:
            # A repeat is the same person: what it adds (an address, how they relate) is kept on the first.
            at = seen[earlier]
            first = found[at]
            found[at] = Pasted(first.name, first.address or person.address, first.relation or person.relation)
            seen.update({k: at for k in keys})
            continue
        seen.update({k: len(found) for k in keys})
        found.append(person)
    return PastedList(found[:_PASTE_LIMIT], left_out)


def on_file(store: Any, pasted: list[Pasted]) -> dict[str, bool]:
    """For each pasted name, whether someone of that name or address is on file already."""
    addresses, names = _known(store)
    return {p.name: p.name.lower() in names or bool(p.address and p.address in addresses) for p in pasted}


def company_words_of(cfg: Any) -> frozenset[str]:
    """The words that name a company or a service rather than a person, from the settings (lower case)."""
    return frozenset(w.strip().lower() for w in cfg.ui.walkthrough.not_people_names if w.strip())


def parse_pasted(text: str) -> list[Pasted]:
    """The people in a pasted list (see `parse_list`), without the lines left out."""
    return parse_list(text).people
