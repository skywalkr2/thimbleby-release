"""Areas of life under the personal project (design 6.32, "Personal life").

An area (`Project.area`) is ongoing and has no end day; a project under it has a goal and an end. Three things
are done here, the first two by rules over the records and the settings with no AI:

- **Reach.** What a draft about a project in an area may draw on stops at that area: the area, the projects inside
  it and the projects above it (the personal project), never a sibling area's facts, open items or knowledge.
- **Reading.** Which accounts may read an area's material (its content levels, and the ones above it) and whether
  reading it sends anything away from this computer.
- **Offers.** Whether items filed under the personal project make an area of the person's life, what to call it and why
  is the assistant's judgment (`engine/area_offers.py`, the `area-read` task kind), kept as offer records. A plain
  rule only narrows what it looks at: items that share a whole word with enough others, a word the language uses every
  day never counting. Only the items' own subject is read: a question the app asks about a held item is its own
  wording, never a source of a name. Nothing is moved until the person says yes, and what they keep is their own edit,
  so a move is recorded as a correction.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from engine import sides
from engine.ai.router import accounts
from engine.ai.smoke import where_of
from engine.language_words import language_words


def area_of(view: Any, project_id: str | None) -> str | None:
    """The area a project is in: itself when it is one, else the nearest project above it that is. None for a project
    in no area, or one that isn't there. A chain that loops stops where it began."""
    seen: set[str] = set()
    current = project_id
    while current and current not in seen:
        seen.add(current)
        record = view.get("project", current)
        if record is None:
            return None
        if record.data.get("area"):
            return current
        current = record.data.get("parent")
    return None


def area_of_line(view: Any, line: Any) -> str | None:
    """The area a line of Today's queue is in: that of its project, else the one area every record it names is in. A
    line about records in several areas, or in none, is in no area."""
    if area := area_of(view, getattr(line, "project", None)):
        return area
    found: set[str] = set()
    refs = [("question", getattr(line, "question", None))]
    refs += [("action", i) for i in getattr(line, "actions", None) or []]
    refs += [("question", i) for i in getattr(line, "questions", None) or []]
    for kind, record_id in refs:
        record = view.get(kind, record_id) if record_id else None
        if record is None:
            continue
        for project in _projects_named(record.data):
            if area := area_of(view, project):
                found.add(area)
    return next(iter(found)) if len(found) == 1 else None


def _projects_named(data: Mapping[str, Any]) -> list[str]:
    return [p for p in sides.projects_of(dict(data)) if p]


def _inside(view: Any, top: str) -> set[str]:
    """The project and every project inside it, at any depth."""
    children: dict[str, list[str]] = {}
    for project in view.list("project"):
        if parent := project.data.get("parent"):
            children.setdefault(parent, []).append(project.id)
    found, todo = {top}, [top]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def _above(view: Any, project_id: str) -> set[str]:
    found: set[str] = set()
    current = project_id
    while current and current not in found:
        found.add(current)
        record = view.get("project", current)
        current = record.data.get("parent") if record is not None else None
    return found


def reach(view: Any, projects: Iterable[str | None]) -> frozenset[str] | None:
    """The projects whose records a draft about `projects` may draw on, when any of them is in an area: each such
    area, the projects inside it and the projects above it. None when none is, which is no limit. A record that
    names no project is never an area's own and is not limited."""
    found: set[str] | None = None
    for project in projects:
        area = area_of(view, project)
        if area is not None:
            found = (found or set()) | _inside(view, area) | _above(view, area)
    return frozenset(found) if found is not None else None


def outside(allowed: frozenset[str] | None) -> Callable[[Mapping[str, Any]], bool]:
    """A test for the records a draft about an area leaves out: true for a record filed under a project outside its
    reach. With no limit nothing is left out."""

    def out(data: Mapping[str, Any]) -> bool:
        if allowed is None:
            return False
        named = [p for p in sides.projects_of(dict(data)) if p]
        return bool(named) and not any(p in allowed for p in named)

    return out


def either(first: Callable[[Mapping[str, Any]], bool] | None, second: Callable[[Mapping[str, Any]], bool]):
    """One test that is true when either is."""
    return second if first is None else lambda data: first(data) or second(data)


# ---- who reads an area ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reader:
    account: str
    name: str
    leaves: bool


@dataclass(frozen=True)
class Reading:
    """Who may read a project's material. `levels`: the content levels it carries (its own and those above it).
    `readers`: the accounts that may read it, in tier order, each saying whether reading sends it away from this
    computer (an address that isn't on this computer or its own network, or a program that talks to its own
    service). `state`: none (no account may), local (every one that may runs here) or away (at least one sends it
    away)."""

    levels: tuple[str, ...]
    readers: tuple[Reader, ...]
    state: str


def levels_of(view: Any, project_id: str) -> tuple[str, ...]:
    """The content levels a project's material carries: its own and those of every project above it."""
    found: dict[str, None] = {}
    for pid in sorted(_above(view, project_id), key=lambda p: p != project_id):
        record = view.get("project", pid)
        for level in (record.data.get("content_levels") if record is not None else None) or []:
            found[level] = None
    return tuple(found)


def reading(view: Any, cfg: Any, project_id: str) -> Reading:
    """Which accounts may read a project's material, from its content levels and what each account takes, and whether
    anything leaves this computer to reach them."""
    levels = levels_of(view, project_id)
    readers = []
    for ref in accounts(cfg, "internal", frozenset(levels)):
        provider_name = ref.partition("/")[0]
        provider = cfg.ai.providers[provider_name]
        if any(r.account == provider_name for r in readers):
            continue
        readers.append(Reader(provider_name, provider.label or provider_name, where_of(provider) != "local"))
    state = "none" if not readers else "away" if any(r.leaves for r in readers) else "local"
    return Reading(levels, tuple(readers), state)


# ---- offering an area ----------------------------------------------------------------------------------------------

#: What each kind's words are called and the statuses that leave it open (an item that has ended is no pattern).
_ITEMS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "action": ("text", ("open", "held")),
    "question": ("title", ("open", "sent")),
    "fact": ("text", None),
    "event": ("title", None),
}


@dataclass(frozen=True)
class Candidate:
    """An item the rule narrowed to for the assistant's reading: its kind, id, read version and words, and the whole
    words it shares with enough other items under the personal project (`shared`, most shared first)."""

    kind: str
    id: str
    version: int
    text: str
    shared: tuple[str, ...]


@dataclass(frozen=True)
class Offer:
    """An area the assistant offered, as it stands now: the offer record's `id`, the `name` it gave the area, its `why`
    and the `items` (kind, id, read version, words) that are still there to take, most recent first."""

    id: str
    name: str
    why: str
    items: tuple[tuple[str, str, int, str], ...]


def _own_items(view: Any, cfg: Any, personal: str) -> list[tuple[str, str, int, str]]:
    replaced = {f.data["supersedes"] for f in view.list("fact") if f.data.get("supersedes")}
    found = []
    for kind, (field, open_statuses) in _ITEMS.items():
        for record in view.list(kind):
            data = record.data
            if sides.projects_of(data) != [personal]:
                continue
            if open_statuses and data.get("status") not in open_statuses:
                continue
            if kind == "fact" and record.id in replaced:
                continue
            if kind == "question" and data.get("resolves"):
                continue  # the app's own question about a held item: its title is its wording, not the item's subject
            found.append((kind, record.id, record.version, str(data.get(field) or "")))
    return found


def _offered_ids(view: Any) -> set[str]:
    """The ids of the items an offer already holds, whatever became of it: they are not offered again."""
    return {i["id"] for o in view.list("area_offer") for i in o.data["items"]}


def narrowed(view: Any, cfg: Any) -> list[Candidate]:
    """The items the assistant is asked about: those filed under the personal project itself that share a whole word
    with enough others (`steward.areas.propose_after`; none when it is zero or there is no personal project), a word the
    language uses every day or that already names a project never counting, and items an earlier offer holds left out.
    A plain rule only narrows: whether the items make an area of the person's life, and what it is called, is the
    assistant's to say. Newest first."""
    from engine.knowledge_section import _overlap_words

    needed = cfg.steward.areas.propose_after
    personal = sides.personal_project(view, cfg)
    if needed <= 0 or personal is None:
        return []
    everyday = {w.strip().lower() for w in language_words(cfg.language, "everyday_words")}
    named = {
        _stem(word)
        for project in view.list("project")
        if project.id in _inside(view, personal) and project.id != personal
        for word in _overlap_words(str(project.data["name"]))
    } | {str(p.data["name"]).strip().lower() for p in view.list("project")}
    held = _offered_ids(view)
    items = [i for i in _own_items(view, cfg, personal) if i[1] not in held]
    words: dict[str, set[str]] = {}
    for _kind, record_id, _, text in items:
        for word in _overlap_words(text):
            if word.isalpha() and word not in everyday and _stem(word) not in everyday and word not in named:
                words.setdefault(word, set()).add(record_id)
    shared_by: dict[str, list[str]] = {}
    for word, ids in sorted(words.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(ids) < needed:
            continue
        shown = _whole_word(word, [i[3] for i in items if i[1] in ids])
        if shown.lower() in named or shown.capitalize().lower() in named:
            continue
        for record_id in ids:
            shared_by.setdefault(record_id, []).append(shown.lower())
    return [
        Candidate(kind, record_id, version, text, tuple(shared_by[record_id]))
        for kind, record_id, version, text in sorted(items, key=lambda i: i[1], reverse=True)
        if record_id in shared_by
    ]


def _whole_word(stem: str, texts: list[str]) -> str:
    """The word the items wrote for a matching stem, the one most of them used (the shorter one on a tie, then the first
    alphabetically). The stem folds plurals so "swatches" and "swatch" meet, but it is not always a word ("swatche"), so
    the words shown are never the stem. With none found the stem stands."""
    from collections import Counter

    from engine.knowledge_section import _PART, _WORD

    counted: Counter[str] = Counter()
    for text in texts:
        for token in _WORD.findall(text):
            for part in _PART.findall(token):
                if len(part) >= 4 and _stem(part) == stem:
                    counted[part.lower()] += 1
    if not counted:
        return stem
    return min(counted, key=lambda w: (-counted[w], len(w), w))


def _stem(word: str) -> str:
    from engine.knowledge_section import _stem as stem

    return stem(word)


def offers(view: Any, cfg: Any) -> list[Offer]:
    """The areas to offer now: each offer the assistant made that waits for the person, with the items of it that are
    still there (still filed under the personal project and open). An offer with fewer than two left, or whose name is
    now a project's, is not shown. Oldest first."""
    personal = sides.personal_project(view, cfg)
    if personal is None:
        return []
    names = {str(p.data["name"]).strip().lower() for p in view.list("project")}
    out: list[Offer] = []
    for record in sorted(view.list("area_offer"), key=lambda r: r.id):
        d = record.data
        if d["status"] != "offered" or d["name"].strip().lower() in names:
            continue
        here = {i[1]: i for i in _own_items(view, cfg, personal)}
        standing = tuple(here[i["id"]] for i in d["items"] if i["id"] in here and here[i["id"]][0] == i["kind"])
        if len(standing) >= 2:
            out.append(Offer(record.id, d["name"], d["why"], standing))
    return out


def find(view: Any, cfg: Any, offer_id: str) -> Offer | None:
    """The offer as it stands now, or None when it no longer stands (fewer items are left, or the area exists)."""
    return next((o for o in offers(view, cfg) if o.id == offer_id), None)


@dataclass(frozen=True)
class Kept:
    """What keeping an offer did: the area made and the two changes to undo, the filing first."""

    project: str
    filed: str
    started: str


def keep(store: Any, cfg: Any, offer_id: str, name: str | None = None) -> Kept:
    """Start the area an offer names under the personal project and file its items under it, each filing the person's
    own edit of the item's project (so a move from the personal project is a correction the assistant learns from), and
    mark the offer kept. Two changes, so the screen can undo both. Raises `StoreError` when the offer no longer stands
    or an item changed since it was offered. `name` is the name the person chose for the area; the offer's own when it
    is empty."""
    from engine.applier import apply_as_person
    from engine.storage import StoreError

    view = store.read()
    offer = find(view, cfg, offer_id)
    if offer is None:
        raise StoreError("That offer no longer stands: fewer of its items are left, or the area is already there.")
    chosen = " ".join((name or "").split()) or offer.name
    if chosen.lower() in {str(p.data["name"]).strip().lower() for p in view.list("project")}:
        raise StoreError(f"You already have something called {chosen}. Choose a different name.")
    personal = sides.personal_project(view, cfg)
    started = apply_as_person(
        store,
        cfg,
        [{"op": "project.add", "name": chosen, "parent": personal, "area": True}],
        f"Started the area {chosen}",
    )
    project = store.read().get("changeset", started).data["ops"][0]["records"][0]["id"]
    ops = [
        {
            "op": "record.edit",
            "record": {"kind": kind, "id": record_id},
            "fields": {("projects" if kind == "question" else "project"): [project] if kind == "question" else project},
            "read_version": version,
        }
        for kind, record_id, version, _ in offer.items
    ]
    record = view.get("area_offer", offer_id)
    ops.append(
        {
            "op": "record.edit",
            "record": {"kind": "area_offer", "id": offer_id},
            "fields": {"status": "kept", "project": project},
            "read_version": record.version,
        }
    )
    filed = apply_as_person(store, cfg, ops, f"Filed {len(offer.items)} items under the area {chosen}")
    return Kept(project, filed, started)
