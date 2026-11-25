"""Every open action and every open question, in one place each (design 7.5).

An open action comes with its owners as the workspace writes them, its due date, its project and that project's parent,
its notes, where it came from, its state, and the open action it most nearly repeats. An open question comes with who it
waits on, since when and its state. The states are for the screen's filter; a row has exactly one. Nothing here calls
AI or changes anything, apart from `merge_actions`, which is the person's own change, applied like any other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from engine import endings, patterns, repeats, sides
from engine.answer_state import answer_states
from engine.applier import _similar, apply_as_person
from engine.blocked import Blocker, blocker_of, overdue_day, own_wait
from engine.followups import ROUTING, actions_to_send, held_until_day
from engine.mail_kinds import TRACKED as TRACKED_MAIL
from engine.names import People, render_owner
from engine.origin import origins, source_origin
from engine.storage import StoreError
from engine.titles import _who
from engine.today import zone
from engine.views import views_of_item

#: An action's state, in the order a row takes the first that applies.
ACTION_STATES = ("no_owner", "on_hold", "overdue", "stale", "open")
#: A question's state.
QUESTION_STATES = ("yours", "reading", "answer_waiting", "waiting", "not_sent", "later")


@dataclass(frozen=True)
class OwnerName:
    person: str
    name: str
    team: str | None = None


@dataclass(frozen=True)
class Alike:
    """The open action another one most nearly repeats: its id, text and version as read."""

    id: str
    text: str
    version: int


@dataclass
class OpenAction:
    id: str
    version: int
    text: str
    state: str
    owners: list[OwnerName]
    due: str | None
    project: str | None
    project_name: str
    parent_name: str | None
    notes: str | None
    since: str
    on_hold: str | None = None
    blocker: Blocker | None = None
    duplicate: Alike | None = None
    origin: dict[str, Any] | None = None
    #: The days since anything changed on it, for a row the screen says is stale.
    untouched_days: int | None = None
    #: For an action with no owner, the open question asking who owns it.
    owner_question: str | None = None
    #: An owner other than the person hasn't been told about it yet (design 6.10).
    to_send: bool = False
    #: The people it reached (told or chased), as shown: who dropping it tells.
    told_names: list[str] = field(default_factory=list)
    #: Its date is one the rules couldn't read for certain: it is shown to be checked and is never a deadline.
    due_check: bool = False
    #: How it repeats, when it does (`engine.repeats.view_of`).
    repeat: dict[str, Any] | None = None
    #: About how long it takes, in minutes, when it says.
    effort_minutes: int | None = None
    #: When the person asked to be reminded of it, on their own clock.
    remind_at: datetime | None = None
    #: The side it is filed on directly, when it is in a side and in no project of it (design 6.32).
    side_name: str | None = None
    #: The side it is on (the id of its top project), whether it is filed on the side itself or in a project of it; none
    #: when it is on none.
    side: str | None = None
    #: The views its project is in, which only change what a screen shows (design 6.32).
    views: list[str] = field(default_factory=list)
    #: Open, with no date, and the person's own or one they told someone about: the screen's "Needs a date" group.
    needs_date: bool = False
    #: The latest day a follow-up to its owners was recorded (a nudge is never completion: the to-do stays open).
    followed_up: str | None = None


@dataclass
class OpenQuestion:
    id: str
    version: int
    title: str
    text: str
    kind: str
    state: str
    to: str
    to_name: str
    project_name: str
    since: str
    projects: list[str] = field(default_factory=list)
    waiting_days: int | None = None
    chases: int = 0
    held_until: str | None = None
    #: Put to the person themself (so a hold on it is theirs to read, not a day to ask someone).
    yours: bool = False
    origin: dict[str, Any] | None = None
    #: The sides it is filed on directly, by name and joined with commas, apart from the projects.
    side_name: str | None = None
    #: The side it is on (the id of the first project it names that is on one); none when it is on none.
    side: str | None = None
    #: The views of the projects it names, which only change what a screen shows (design 6.32).
    views: list[str] = field(default_factory=list)
    #: For an answered question whose answer is not judged yet: why the run can't go, in its own words.
    answer_why: str | None = None


def waits_on_person(action: OpenAction, me: str | None) -> bool:
    """Whether a to-do waits on the person: theirs, or with no owner yet, and not on hold. The one rule behind the side
    menu's count and each row's mark on the screen, so the two never disagree."""
    if action.state == "on_hold":
        return False
    return action.state == "no_owner" or (me is not None and any(o.person == me for o in action.owners))


def _last_chase(d: dict[str, Any]) -> str | None:
    """The latest day a follow-up was recorded on an action, over all its owners."""
    days = [str(day) for chases in (d.get("followed_up") or {}).values() for day in chases]
    return max(days) if days else None


def _day(stamp: str | None, here: Any) -> date | None:
    if not stamp:
        return None
    moment = datetime.fromisoformat(str(stamp))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(here).date()


def _moment(stamp: str) -> datetime:
    at = datetime.fromisoformat(stamp)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def open_actions(
    store: Any, cfg: Any, today: date, *, now: datetime | None = None, light: bool = False
) -> list[OpenAction]:
    """Every action still to do (open or waiting for an owner), overdue first, then by date, undated last. With `light`,
    the rows leave out what costs a pass over all of them (the near-duplicate each offers and where it came from), for a
    caller that only needs their states."""
    now = now or datetime.combine(today, time.max, tzinfo=UTC)
    here = zone(cfg)
    view = store.read()
    people = People(store, cfg)
    projects = {p.id: p.data for p in view.list("project")}
    names = sides.project_names(view, cfg)
    changed = view.last_changes("action")
    created = view.creators("action")
    stale_after = cfg.ui.today.stale_after_days
    kept = patterns.marks(view) if stale_after else {}
    me = cfg.workspace.user.person
    asking_owner = {
        (q.data.get("resolves") or {}).get("action"): q.id
        for q in view.list("question")
        if q.data["status"] == "open" and (q.data.get("resolves") or {}).get("kind") == "owner"
    }
    rows: list[OpenAction] = []
    to_send = actions_to_send(store, cfg)
    for a in view.list("action"):
        d = a.data
        if d["status"] not in ("open", "held"):
            continue
        hold = d.get("on_hold")
        blocker = blocker_of(view, hold, people, here)
        if blocker is not None and blocker.resolved:
            hold = None  # what it waited on is over, so it is due again by its own date
        elif own_wait(view, d, people.pm):
            hold, blocker = None, None  # it waits on the person themselves: their own to-do, not blocked
        due = date.fromisoformat(str(d["due"])) if d.get("due") else None
        project = projects.get(d.get("project") or "")
        owners = [
            OwnerName(
                o["person"],
                render_owner(people.owner_format, people.name(o["person"]), people.team_names.get(o.get("team") or "")),
                o.get("team"),
            )
            for o in d.get("owners") or []
        ]
        # What the person said about a stale line (kept it, snoozed it) counts as a touch, and a snooze waits.
        mark = kept.get(a.id)
        touched = _moment(changed[a.id]) if a.id in changed else None
        if mark is not None and (touched is None or mark.at > touched):
            touched = mark.at
        untouched = (now - touched).days if touched is not None else None
        snoozed = mark is not None and mark.until is not None and mark.until > now
        own = bool(me) and any(o["person"] == me for o in d.get("owners") or [])
        if d["status"] == "held":
            state = "no_owner"
        elif hold:
            state = "on_hold"
        elif overdue_day(view, d, today, people, here) is not None:
            state = "overdue"
        elif (
            stale_after
            and own
            and due is None
            and not d.get("remind_at")
            and not d.get("reply_owed")
            and not snoozed
            and untouched is not None
            and untouched >= stale_after
        ):
            state = "stale"
        else:
            state = "open"
        told = endings.told_names(view, cfg, people, a)
        rows.append(
            OpenAction(
                id=a.id,
                version=a.version,
                text=d["text"],
                state=state,
                owners=owners,
                due=due.isoformat() if due else None,
                project=d.get("project"),
                project_name=names.get(d.get("project") or "", ""),
                parent_name=names.get((project or {}).get("parent") or ""),
                side_name=sides.side_name_of(view, cfg, d.get("project")),
                side=sides.side_of_item(view, cfg, a),
                views=views_of_item(view, a),
                notes=d.get("notes") or None,
                since=(_day(created[a.id][1], here) or today).isoformat() if a.id in created else "",
                on_hold=hold["waiting_for"] if hold else None,
                blocker=blocker,
                untouched_days=untouched if state == "stale" else None,
                owner_question=asking_owner.get(a.id) if state == "no_owner" else None,
                to_send=a.id in to_send,
                told_names=told,
                due_check=bool(d.get("due_check")) and due is not None,
                repeat=repeats.view_of(d.get("repeat")),
                effort_minutes=d.get("effort_minutes"),
                remind_at=datetime.fromisoformat(str(d["remind_at"])).astimezone(here) if d.get("remind_at") else None,
                followed_up=_last_chase(d),
                needs_date=due is None
                and state in ("open", "stale")
                and not d.get("reply_owed")
                and (own or bool(told)),
            )
        )
    if not light:
        _offer_duplicates(rows, cfg, view)
        found = origins(view, "action", [r.id for r in rows])
        for r in rows:
            r.origin = found.get(r.id)
    order = {state: n for n, state in enumerate(ACTION_STATES)}
    return sorted(rows, key=lambda r: (r.state != "overdue", r.due is None, r.due or "", order[r.state], r.text))


@dataclass
class DoneAction:
    """A to-do closed in the last days, with who closed it and, for the assistant's own close, the words it quoted."""

    id: str
    version: int
    text: str
    closed_at: str
    #: The day it was closed on the person's own clock, as YYYY-MM-DD.
    day: str
    #: `you` for the person's own close (a tick, a note, "they finished it", a held close they released) or `assistant`
    #: for a close the assistant made on its own from an input.
    closed_by: str
    #: The people credited with the work, other than the person.
    done_by: list[str]
    #: Who reported it as finished, when that is somebody other than the person.
    reported_by: str | None
    #: For the assistant's close, the exact words it quoted, clipped; none when it quoted none. A screen shows them only
    #: when the person opens the row.
    reason: str | None
    #: For the assistant's close, what kind of input its quoted words came from, as the app holds it: `reply` (a mail
    #: from a sender), `notice` (a bill, order or delivery mail), `calendar` (a calendar entry), `note` (the person's
    #: own note), or none when the evidence names no input the app can say more about.
    source_kind: str | None
    #: For a `notice`, which kind (bill, order or delivery), as the sorting named it.
    notice: str | None
    #: For a `reply`, the sender's name as the input gives it.
    source_by: str | None
    #: The day the input arrived, as YYYY-MM-DD on the person's own clock; none when the evidence names no input.
    source_day: str | None
    #: The input the quoted words are in, as a row's "where it came from" link opens it.
    origin: dict[str, Any] | None
    project: str | None
    project_name: str
    side_name: str | None
    side: str | None
    views: list[str]


_NO_EVIDENCE: dict[str, Any] = {
    "source_kind": None,
    "notice": None,
    "source_by": None,
    "source_day": None,
    "origin": None,
}


def who_named(sender: str | None, people: People) -> str | None:
    """The sender's name as the input gives it, with an address's own parts left out; the person's full name when the
    sender is one known person."""
    person, shown = _who(sender, people)
    return people.name(person) if person else shown


def _clip(text: str, limit: int) -> str:
    words = " ".join(text.split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "\u2026"


def closed_by_assistant(row: dict[str, Any]) -> bool:
    """Whether a ledger entry that set an action's status was the assistant's own close (its `action.close` op under its
    own name); a held close the person released is written as the person's."""
    return row["actor"] == "assistant" and str(row["op"]).startswith("action.close")


def latest_close(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The latest of an action's ledger entries that set its status to done, or None."""
    return next((r for r in reversed(rows) if r["field"] == "status" and r["after"] == "done"), None)


def last_close(view: Any) -> dict[str, dict[str, Any]]:
    """For each action, the latest ledger entry that set its status to done, by the action's id."""
    found: dict[str, dict[str, Any]] = {}
    for row in view.ledger(kind="action", fields=["status"]):
        if row["after"] == "done":
            found[row["record_id"]] = row
    return found


def _evidence_of(view: Any, people: People, here: Any, row: dict[str, Any]) -> dict[str, Any]:
    """What the app holds about the input an assistant's close quoted: its kind, its sender or notice kind, the day it
    arrived and its origin. Facts from the records only (the source, its request's sorting); never the model's words."""
    none: dict[str, Any] = {"source_kind": None, "notice": None, "source_by": None, "source_day": None, "origin": None}
    cited = (row.get("evidence") or {}).get("source")
    if cited == "note":
        return {**none, "source_kind": "note"}
    source = view.get("source", cited) if cited else None
    if source is None:
        return none
    data = source.data
    day = _day(str(data["received_at"]), here)
    found = {**none, "source_day": day.isoformat() if day else None, "origin": source_origin(source)}
    kind = str(data.get("kind") or "")
    if kind.endswith(":calendar"):
        return {**found, "source_kind": "calendar"}
    if kind.endswith(":mailbox"):
        request = view.get("request", row["request"]) if row.get("request") else None
        sorted_as = request.data.get("mail_kind") if request is not None else None
        if sorted_as in TRACKED_MAIL:
            return {**found, "source_kind": "notice", "notice": sorted_as}
        sender = ((data.get("watched") or {}).get("author")) or None
        return {**found, "source_kind": "reply", "source_by": who_named(sender, people)}
    return found


def done_actions(store: Any, cfg: Any, now: datetime) -> list[DoneAction]:
    """The to-dos closed in the last `ui.done_days` days, newest first: who closed each (the person, or the assistant
    with the words it quoted) and who was credited. Older ones are found by search. Nothing here changes anything."""
    here = zone(cfg)
    view = store.read()
    people = People(store, cfg)
    me = cfg.workspace.user.person
    names = sides.project_names(view, cfg)
    since = now - timedelta(days=cfg.ui.done_days)
    closed = last_close(view)
    rows: list[tuple[datetime, DoneAction]] = []
    for a in view.list("action"):
        d = a.data
        row = closed.get(a.id)
        if d["status"] != "done" or row is None:
            continue
        at = _moment(row["at"])
        if at < since:
            continue
        by_assistant = closed_by_assistant(row)
        quote = ((row.get("evidence") or {}).get("quote") or "") if by_assistant else ""
        reported = d.get("reported_by")
        rows.append(
            (
                at,
                DoneAction(
                    id=a.id,
                    version=a.version,
                    text=d["text"],
                    closed_at=at.isoformat(),
                    day=at.astimezone(here).date().isoformat(),
                    closed_by="assistant" if by_assistant else "you",
                    done_by=[people.name(p) for p in d.get("done_by") or [] if p != me],
                    reported_by=people.name(reported) if reported and reported != me else None,
                    reason=_clip(quote, 600) or None,
                    **(_evidence_of(view, people, here, row) if by_assistant else _NO_EVIDENCE),
                    project=d.get("project"),
                    project_name=names.get(d.get("project") or "", ""),
                    side_name=sides.side_name_of(view, cfg, d.get("project")),
                    side=sides.side_of_item(view, cfg, a),
                    views=views_of_item(view, a),
                ),
            )
        )
    rows.sort(key=lambda r: (r[0], r[1].id), reverse=True)
    return [r for _, r in rows]


def _offer_duplicates(rows: list[OpenAction], cfg: Any, view: Any) -> None:
    """Give each action the one most like it among those of the same project and the same owners, when it is as alike
    as the near-duplicate lint says. An action waiting for an owner, or on hold, is not offered: it isn't the same
    work."""
    needed = cfg.checks.tuning.near_duplicate_action.similarity
    groups: dict[tuple[Any, frozenset[str]], list[OpenAction]] = {}
    for r in rows:
        if r.state in ("no_owner", "on_hold"):
            continue
        groups.setdefault((r.project, frozenset(o.person for o in r.owners)), []).append(r)
    for group in groups.values():
        for r in group:
            best: tuple[float, OpenAction] | None = None
            for other in group:
                if other is r:
                    continue
                score = _similar(r.text, other.text)
                if score >= needed and (best is None or score > best[0]):
                    best = (score, other)
            if best is not None:
                r.duplicate = Alike(best[1].id, best[1].text, best[1].version)


def undated_new_actions(store: Any, cfg: Any, now: datetime) -> list[OpenAction]:
    """The to-dos that need a date and were added in the last `steward.dates.undated_line_days` days, oldest first. None
    when the setting is zero. Older ones are the stale rule's."""
    days = cfg.steward.dates.undated_line_days
    if not days:
        return []
    today = now.astimezone(zone(cfg)).date()
    first = (today - timedelta(days=days)).isoformat()
    found = [r for r in open_actions(store, cfg, today, now=now, light=True) if r.needs_date and r.since >= first]
    return sorted(found, key=lambda r: (r.since, r.id))


def stale_actions(store: Any, cfg: Any, now: datetime) -> list[OpenAction]:
    """The person's own open to-dos with no date that nothing has touched for `ui.today.stale_after_days`, the longest
    untouched first. None when the setting is zero."""
    if not cfg.ui.today.stale_after_days:
        return []
    today = now.astimezone(zone(cfg)).date()
    found = [r for r in open_actions(store, cfg, today, now=now, light=True) if r.state == "stale"]
    return sorted(found, key=lambda r: (-(r.untouched_days or 0), r.id))


def open_questions(store: Any, cfg: Any, today: date, now: datetime | None = None) -> list[OpenQuestion]:
    """Every question still waiting: those to the person first, then what was sent (longest wait first), then what is
    not sent yet, then what is held for later. A question asked only to place a name or pick an owner is answered where
    that waits, so it isn't here."""
    here = zone(cfg)
    view = store.read()
    people = People(store, cfg)
    projects = sides.project_names(view, cfg)
    created = view.creators("question")
    rows: list[OpenQuestion] = []
    unjudged = answer_states(view, now)
    for q in view.list("question"):
        d = q.data
        reading = unjudged.get(q.id)
        if (d["status"] not in ("open", "sent") and reading is None) or (d.get("resolves") or {}).get(
            "kind"
        ) in ROUTING:
            continue
        sent = _day(d.get("sent_at"), here) if d.get("sent_at") else None
        chased = sorted(date.fromisoformat(str(c)) for c in d.get("followed_up") or [])
        last_word = chased[-1] if chased else sent
        held_until, _name = held_until_day(view, d.get("held_for"), today, here)
        if reading is not None:
            state = "reading" if reading.state == "reading" else "answer_waiting"
        elif d["status"] == "sent":
            state = "waiting"
        elif held_until is not None and held_until > today:
            state = "later"
        elif d["to"] == people.pm:
            state = "yours"
        else:
            state = "not_sent"
        began = sent or (_day(created[q.id][1], here) if q.id in created else None)
        rows.append(
            OpenQuestion(
                id=q.id,
                version=q.version,
                title=d["title"],
                text=d.get("text", ""),
                kind=d["kind"],
                state=state,
                to=d["to"],
                to_name=people.name(d["to"]),
                project_name=", ".join(projects[p] for p in d.get("projects", []) if p in projects),
                projects=[p for p in d.get("projects", []) if p in projects],
                side_name=", ".join(
                    n for p in d.get("projects", []) if (n := sides.side_name_of(view, cfg, p)) is not None
                )
                or None,
                side=sides.side_of_item(view, cfg, q),
                views=views_of_item(view, q),
                since=began.isoformat() if began else "",
                waiting_days=max(0, (today - last_word).days) if last_word and state == "waiting" else None,
                chases=len(chased),
                held_until=held_until.isoformat() if state == "later" and held_until else None,
                yours=d["to"] == people.pm,
                answer_why=reading.why if reading is not None else None,
            )
        )
    found = origins(view, "question", [r.id for r in rows])
    for r in rows:
        r.origin = found.get(r.id)
    order = {state: n for n, state in enumerate(QUESTION_STATES)}
    return sorted(rows, key=lambda r: (order[r.state], -(r.waiting_days or 0), r.since, r.id))


def merge_actions(store: Any, cfg: Any, keep: str, other: str, read_version: int, other_version: int) -> str:
    """Keep the action `keep` and close `other`, which it nearly repeats, as one change with one Undo. The kept action's
    notes gain a line with the other's words (and its notes), it takes the earlier of the two due dates, and the other
    is dropped with a reason naming the one it went into: the person's own drop, so it is a correction the assistant
    learns from. `read_version` and `other_version` are the versions the person saw; if either action changed, is not
    open, or they are the same action, nothing changes. Returns the changeset's id."""
    if keep == other:
        raise StoreError("that is the same action")
    view = store.read()
    kept, closed = view.get("action", keep), view.get("action", other)
    if kept is None or closed is None:
        raise StoreError("one of those actions is gone")
    if kept.data["status"] != "open" or closed.data["status"] != "open":
        raise StoreError("only an open action can be merged")
    if kept.version != read_version or closed.version != other_version:
        raise StoreError("one of those actions changed since it was read")
    words = cfg.language.messages
    line = words.merged_note.format(text=closed.data["text"])
    if closed.data.get("notes"):
        line = f"{line}\n{closed.data['notes']}"
    notes = f"{kept.data['notes']}\n{line}" if kept.data.get("notes") else line
    fields: dict[str, Any] = {"notes": notes}
    dues = sorted(str(x.data["due"]) for x in (kept, closed) if x.data.get("due"))
    if dues and dues[0] != str(kept.data.get("due") or ""):
        fields["due"] = dues[0]
    ops = [
        {"op": "record.edit", "record": {"kind": "action", "id": keep}, "fields": fields, "read_version": read_version},
        {"op": "action.drop", "id": other, "reason": words.merged_reason.format(text=kept.data["text"])},
    ]
    return apply_as_person(store, cfg, ops, "Merged two to-dos", all_or_nothing=True)


__all__ = [
    "ACTION_STATES",
    "QUESTION_STATES",
    "Alike",
    "OpenAction",
    "OpenQuestion",
    "OwnerName",
    "merge_actions",
    "open_actions",
    "open_questions",
    "stale_actions",
    "undated_new_actions",
]
