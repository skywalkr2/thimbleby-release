"""Checking a guess from what the person taught (design 6.7, guesses): one small run when a to-do lands on the person
on a project where something they taught waits for their Keep.

What a correction taught (a routing entry that names a kind of work and who does it) waits for the person's Keep and,
until then, is only a guess. The run that makes a to-do sees it, and the cheapest models often pass it by. So when an
assistant's change leaves an open to-do owned by the person alone, on a project a waiting entry applies to, and the
entry names someone else, **one** request is queued in the same transaction as the change. Which to-dos and entries are
paired is found here, by code, from the stored records: that narrows what the assistant looks at. Whether a to-do is
that kind of work is the assistant's judgment: the run is asked, for each pair, and answers by handing the to-do to the
entry's person, marked as a guess the person can take back in one click, or with nothing.

One hop: what a guess-fit run changes never starts another. Nothing here calls AI except the run itself.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from engine.storage.store import WriteContext
from engine.untrusted import neutralize

log = logging.getLogger(__name__)

TASK = "guess-fit"
#: What a guess-fit run may do: give a to-do to the person a waiting entry names.
OPS = ("action.owners",)

_ENGINE = WriteContext(actor="engine", trust="trusted", op="guess_fit.queue")
_CLOSE = WriteContext(actor="engine", trust="trusted", op="guess_fit.close")

NOTHING_TO_CHECK = "Nothing was left to check against what you taught."
NOTHING_FIT = "Nothing here was that kind of work."
OFF = "Checking guesses is switched off."


def _waiting(entry: Any) -> bool:
    """Whether a lesson or routing entry is a guess still waiting for the person's Keep that names a kind of work."""
    data = entry.data
    return bool(data.get("status") == "proposed" and data.get("guess_until_kept") and data.get("kind_of_work"))


def _entries(view: Any) -> list[Any]:
    return [e for kind in ("routing_entry", "lesson") for e in view.list(kind) if _waiting(e)]


def _people_of(view: Any, cfg: Any) -> Any:
    """The people as plain records, to read whom an entry's words name."""
    from engine.language_words import language_words
    from engine.names import People

    return People.from_records(
        {p.id: p.data for p in view.list("person")},
        cfg.workspace.user.person,
        self_words=language_words(cfg.language, "self_words"),
    )


def named_for(entry: Any, people: Any, pm: str | None) -> list[str]:
    """The people a waiting entry gives its kind of work to, never the person themselves: a routing entry's person (none
    when it says who does not do it), and for a lesson the people its scope or its own words name."""
    from engine.knowledge_section import _scope

    data = entry.data
    if entry.kind == "routing_entry":
        named = [] if data.get("negative") else [data.get("person")]
    else:
        named = [*_scope(entry).people, *sorted(people.mentioned_in(str(data.get("text") or "")))]
    return [p for p in dict.fromkeys(named) if p and p != pm]


def _on_project(view: Any, cfg: Any, entry: Any, project: str) -> bool:
    """Whether a waiting entry applies to a project: its scope names the project or one above it, or the kind of work
    it names the project in words."""
    from engine.knowledge_section import _scope, projects_named_in, with_ancestors

    scope = _scope(entry)
    if scope.scope == "projects" and set(scope.projects) & set(with_ancestors(view, [project])):
        return True
    return project in set(projects_named_in(view, " ".join(str(entry.data["kind_of_work"]).split()), cfg))


def _persons_alone(action: Any, pm: str) -> bool:
    """Whether an open action is owned by the person and nobody else, and no guess is marked on it."""
    data = action.data
    owners = [o.get("person") for o in data.get("owners") or []]
    return data.get("status") == "open" and owners == [pm] and not data.get("by_kind")


def pairs_for(view: Any, cfg: Any, action_ids: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """Each open to-do of these that the person owns alone, paired with each waiting entry that applies to its project
    and gives its work to someone else, as {action, entry}; and the to-dos that a waiting entry reaches but none can
    be checked against (every such entry names no one else), as ids."""
    pm = cfg.workspace.user.person
    if not pm:
        return [], []
    entries = _entries(view)
    if not entries:
        return [], []
    people = _people_of(view, cfg)
    pairs: list[dict[str, str]] = []
    unmatched: list[str] = []
    for action_id in dict.fromkeys(action_ids):
        action = view.get("action", action_id)
        project = action.data.get("project") if action is not None else None
        if action is None or not project or not _persons_alone(action, pm):
            continue
        reaching = [e for e in entries if _on_project(view, cfg, e, project)]
        usable = [e for e in reaching if named_for(e, people, pm)]
        pairs += [{"action": action_id, "entry": e.id} for e in usable]
        if reaching and not usable:
            unmatched.append(action_id)
    return pairs, unmatched


def said_of(note: str, action: Any) -> str:
    """The sentence of the person's own note a to-do came from: the one holding its evidence quote, else the one sharing
    most of its words (at least half), else none."""
    from engine.cleaning import normalize

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", note or "") if s.strip()]
    quote = normalize(((action.data.get("evidence") or {}).get("quote")) or "")
    for sentence in sentences:
        plain = normalize(sentence)
        if quote and (quote in plain or plain in quote):
            return sentence
    words = {w for w in re.findall(r"\w+", action.data.get("text", "").casefold()) if len(w) > 3}
    best, share = "", 0.0
    for sentence in sentences:
        found = len(words & set(re.findall(r"\w+", sentence.casefold()))) / len(words) if words else 0.0
        if found > share:
            best, share = sentence, found
    return best if share >= 0.5 else ""


def taken_by_person(note: str, action: Any, cfg: Any) -> bool:
    """Whether the person's own note took the to-do themselves ("I'll send them myself"): the sentence it came from
    holds one of the language's own-promise words. A rule on the person's own words: such a to-do is never offered to a
    guess."""
    from engine.language_words import language_words

    sentence = said_of(note, action).replace("\u2019", "'").casefold()
    mine = [w.replace("\u2019", "'").casefold() for w in language_words(cfg.language, "own_promise_words") if w.strip()]
    return bool(sentence) and any(re.search(rf"(?<![\w']){re.escape(w)}(?![\w'])", sentence) for w in mine)


def _own_note(request: Any) -> str:
    """The person's own words a request carries: their typed note, never outside text."""
    if request is None or request.data.get("origin") != "pm":
        return ""
    return str(request.data.get("note") or "")


def queue(tx: Any, cfg: Any, now: str) -> str | None:
    """Queue the request for the to-dos this transaction gave the person, inside it: one request however many. Nothing
    is queued when checking is off, when the change is not an assistant's, when it is a guess-fit run's own (one hop),
    when no open to-do it made or handed over is the person's alone, or when no waiting entry applies. Returns the
    request id. When a guess waits on a project and such a to-do went to the person but nothing is queued, the reason
    is logged, by ids only."""
    changeset_id = tx.changeset
    changeset = tx.get("changeset", changeset_id) if changeset_id else None
    if changeset is None or not changeset.data.get("run"):
        return None  # the person's own act, or no change at all: never second-guessed
    request = tx.get("request", changeset.data["request"])
    if request is not None and request.data["task"] == TASK:
        return None
    made = [
        rid
        for kind, rid, version, field, _, _, _ in tx.pending
        if kind == "action" and (version == 1 or field == "owners")
    ]
    if not made:
        return None
    pairs, unmatched = pairs_for(tx, cfg, made)
    note = _own_note(request)
    if note:
        taken = {p["action"] for p in pairs if taken_by_person(note, tx.get("action", p["action"]), cfg)}
        for action_id in sorted(taken):
            log.warning("guess fit: %s taken by the person in their own note", action_id)
        pairs = [p for p in pairs if p["action"] not in taken]
    if not cfg.dispatch.knowledge.apply_guesses:
        if pairs or unmatched:
            log.warning(
                "guess fit: switched off; %s given to the person, entries %s",
                ", ".join(sorted({p["action"] for p in pairs} | set(unmatched))),
                ", ".join(sorted({p["entry"] for p in pairs})) or "none that name someone else",
            )
        return None
    for action_id in unmatched:
        log.warning("guess fit: %s given to the person; no waiting entry that reaches it names someone else", action_id)
    if not pairs:
        return None
    return tx.create("request", _data(changeset_id, pairs, now), _ENGINE).id


def _data(follows: str | None, pairs: list[dict[str, str]], now: str) -> dict[str, Any]:
    return {
        "task": TASK,
        "about": {"kind": "action", "id": pairs[0]["action"]},
        "origin": "schedule",
        "state": "queued",
        "waiting": "With the assistant, starting now",
        "follows": follows,
        "pairs": pairs,
        "created_at": now,
    }


def queue_open(store: Any, cfg: Any, now: str) -> str | None:
    """Queue the request for every open to-do the person owns alone that a waiting entry reaches, outside a change (the
    evaluation cases start here). Returns the request id, or None when there is nothing to check."""
    view = store.read()
    pairs, _ = pairs_for(view, cfg, [a.id for a in view.list("action")])
    if not pairs or not cfg.dispatch.knowledge.apply_guesses:
        return None
    with store.transaction() as tx:
        return tx.create("request", _data(None, pairs, now), _ENGINE).id


def live_pairs(view: Any, cfg: Any, request: Mapping[str, Any]) -> list[dict[str, str]]:
    """The request's pairs that still stand: the to-do is open, the person's alone and not marked, and the entry is
    still a waiting guess that gives its work to someone else."""
    pm = cfg.workspace.user.person
    people = _people_of(view, cfg)
    found = []
    for pair in request.get("pairs") or []:
        action, entry = view.get("action", pair["action"]), _entry(view, pair["entry"])
        if action is None or entry is None or not pm or not _persons_alone(action, pm):
            continue
        if _waiting(entry) and named_for(entry, people, pm):
            found.append(pair)
    return found


def _entry(view: Any, entry_id: str) -> Any | None:
    """The lesson or routing entry an id names, or None."""
    from engine.learn import kind_of_id
    from engine.records import REGISTRY

    kind = kind_of_id(REGISTRY, entry_id)
    return view.get(kind, entry_id) if kind in ("lesson", "routing_entry") else None


def skip_reason(store: Any, cfg: Any, request: Mapping[str, Any]) -> str | None:
    """Why a guess-fit request has nothing to do any more, in plain words, or None: checking is off, or no pair still
    stands (the to-do is done, went to someone, carries a guess already, or the lesson was kept or discarded)."""
    if not cfg.dispatch.knowledge.apply_guesses:
        return OFF
    if not live_pairs(store.read(), cfg, request):
        return NOTHING_TO_CHECK  # nothing for a run to look at: no packet, no estimate, no call
    return None


def close(store: Any, request_id: str, why: str) -> None:
    """Finish a guess-fit request that has nothing to do, saying why."""
    with store.transaction() as tx:
        current = tx.get("request", request_id)
        if current is not None and (current.data["state"], current.data.get("waiting")) != ("done", why):
            tx.update(
                "request",
                request_id,
                {"state": "done", "waiting": why, "cause": None},
                _CLOSE,
                read_version=current.version,
            )


def closed_quietly(request: Mapping[str, Any]) -> bool:
    """Whether a guess-fit request ended with nothing changed: it was dropped before a call, or nothing was that kind of
    work. The list of what changed leaves it out."""
    return (
        request.get("task") == TASK
        and request.get("state") == "done"
        and request.get("waiting") in (OFF, NOTHING_TO_CHECK, NOTHING_FIT)
    )


def finish(store: Any, request_id: str, changeset_id: str) -> None:
    """A guess-fit run was applied. An answer with no change in it needs no review: the request is done."""
    with store.transaction() as tx:
        found = tx.get("changeset", changeset_id)
        current = tx.get("request", request_id)
        if found is None or current is None or found.data["ops"]:
            return
        tx.update(
            "request", request_id, {"state": "done", "waiting": NOTHING_FIT}, _CLOSE, read_version=current.version
        )


def with_marks(changeset: Any, request: Mapping[str, Any]) -> Any:
    """Every hand-over in a guess-fit answer is marked as a guess, whether or not the run named its step: a step on a
    paired to-do with no `by_kind` of its own is named for the pair's entry. A step the run named is left as it
    named it (the check refuses a wrong one). Marking decides nothing: the run chose to hand the to-do over."""
    named = {step.op for step in changeset.by_kind}
    by_action: dict[str, list[str]] = {}
    for pair in request.get("pairs") or []:
        by_action.setdefault(pair["action"], []).append(pair["entry"])
    added = [
        {"op": i, "entry": by_action[op.id][0]}
        for i, op in enumerate(changeset.ops)
        if getattr(op, "op", None) == "action.owners" and i not in named and op.id in by_action
    ]
    if not added:
        return changeset
    from engine.ops import ByKindStep

    return changeset.model_copy(update={"by_kind": [*changeset.by_kind, *(ByKindStep(**a) for a in added)]})


def reach_problem(view: Any, request: Mapping[str, Any], index: int, op: Any, steps: list[Any]) -> str | None:
    """Why a step of a guess-fit answer reaches past what it may do, or None: an owner change on a to-do the request
    didn't pair, one given to anyone but its entry's person, or a step that names an entry not paired with its to-do."""
    if getattr(op, "op", None) != "action.owners":
        return "a check of a guess may only change who owes a to-do it was given"
    pairs = [p for p in request.get("pairs") or [] if p["action"] == op.id]
    if not pairs:
        return f"{op.id} is not one of the to-dos to check; leave it out"
    named = [s.entry for s in steps if s.op == index]
    if any(entry not in {p["entry"] for p in pairs} for entry in named):
        return f"the entry named for step {index} is not one checked against {op.id}; name one that is, or leave it out"
    return None


def owners_problem(ctx: Any, request: Mapping[str, Any], op: Any, steps: list[Any], index: int) -> str | None:
    """Why the owners an `action.owners` step gives are not the people the entry its pair names gives its work to (the
    entry the step names, when it names one), or None."""
    view = ctx.store.read()
    pm = ctx.cfg.workspace.user.person
    people = _people_of(view, ctx.cfg)
    named = {s.entry for s in steps if s.op == index}
    allowed: set[str] = set()
    for pair in request.get("pairs") or []:
        if pair["action"] == op.id and (not named or pair["entry"] in named):
            entry = _entry(view, pair["entry"])
            allowed |= set(named_for(entry, people, pm)) if entry is not None else set()
    given = {ctx.people.resolve(o).person for o in op.owners}
    if not given <= allowed:
        return f"{op.id} may only be given to the person its lesson names, not to anyone else"
    return None


# ---- the packet ------------------------------------------------------------------------------------------------------


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date) -> Any:
    """The packet for one guess-fit run. Stable first: the instructions, the op reference, the practice, what has been
    learned, the people and the projects. Then the request: each to-do (as outside text, since its words may come from
    an input) with its project, and the entry to check it against: the kind of work it names, its own words and the
    person it names."""
    from dataclasses import replace

    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.names import PacketPeople
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _people, _projects, _task
    from engine.prompts import render

    view = store.read()
    pairs = live_pairs(view, cfg, req.data)
    if not pairs:
        raise PacketRefused("nothing is left to check against what you taught")
    people = PacketPeople(store, cfg)
    plain = _people_of(view, cfg)
    pm = cfg.workspace.user.person
    followed = view.get("changeset", req.data["follows"]) if req.data.get("follows") else None
    note = _own_note(view.get("request", followed.data["request"]) if followed is not None else None)
    blocks = []
    projects: list[str] = []
    words = []
    for number, pair in enumerate(pairs, start=1):
        action, entry = view.get("action", pair["action"]), _entry(view, pair["entry"])
        project = view.get("project", action.data["project"])
        if project is not None and project.id not in projects:
            projects.append(project.id)
        kind_of_work = " ".join(str(entry.data["kind_of_work"]).split())
        who = ", ".join(f"{people.name(p)} ({p})" for p in named_for(entry, plain, pm))
        taught = " ".join(str(entry.data["text"]).split())
        words.append(f"{action.data['text']} {kind_of_work} {taught}")
        blocks.append(
            f"## Pair {number}\n"
            f"To-do {action.id}, on the project {project.data['name'] if project else action.data['project']}, "
            f"owned by you:\n"
            f'<untrusted source="records">\n{neutralize(action.data["text"])}\n</untrusted>\n'
            f"Taught, {entry.id}: the kind of work is {kind_of_work}. Whose work it is: {who}.\n"
            f"Your own words when you taught it: {taught}"
            + (f"\nYour own words when this to-do came in: {said}" if (said := said_of(note, action)) else "")
        )
    learned = _learned(
        store,
        cfg,
        kind,
        people,
        projects=projects,
        source=None,
        text="\n".join(words),
        today=today,
    )
    instructions = render(kind.prompt, {"assistant_name": cfg.workspace.assistant_name}, ws.root, kind.prompt_file)
    stable = "\n\n".join(
        part
        for part in (
            "# Op reference\n" + reference_for(list(kind.ops), store.plugins.ops, reach=reach_choices(store.plugins)),
            "# Practice\n" + _guidance(kind),
            learned.stable,
            "# People\n" + _people(store, cfg),
            "# Projects\n" + _projects(store, cfg),
        )
        if part.strip()
    )
    request = "\n\n".join(
        part
        for part in (
            f"Today is {today.isoformat()} ({today.strftime('%A')}).",
            learned.per_input,
            "# The to-dos to check, each with what you taught\n\n" + "\n\n".join(blocks),
            "For each pair: if the to-do is that kind of work, give it to the person named and name the step in "
            '"by_kind"; if it is not, leave it out.',
        )
        if part
    )
    task = replace(_task(cfg, store, kind, instructions, stable, request), knowledge=learned.log.model_dump())
    return Packet(
        task,
        request,
        Cleaned("", 0, 0, False, 0),
        "",
        too_long=False,
        untrusted_material=False,
        cites=f"guess-fit:{req.id}",
        data_level=_data_level(store, req.data),
        knowledge=learned.log,
    )
