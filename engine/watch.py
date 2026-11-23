"""Watchers (design 6.4): each source in `watch.yaml` is read on its schedule through its connector, compared with
what was seen last time, and every real difference is handed in for the assistant to read, like something the person
pasted, but marked as outside content.

- A source's first read is taken in quietly (`first_run: intake`, see `engine/source_intake.py`): nothing is reported
  as new one by one. `baseline` only notes what is there, so connecting a full folder doesn't hand in everything it
  holds; `recent` also hands in the last hours; `all` hands everything in.
- A changed item is handed in with a readable diff and its text now; a new one with its text; one that disappeared
  from a complete listing, as gone (unless the source turns that off).
- No network is not a failure and files nothing. A source that fails `failures_before_asking` reads in a row files one
  question to the person, not one per read; a read that works again ends it.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from engine import audience, entry_rules, version_choices, versions
from engine.connectors import (
    CORE,
    Connector,
    ConnectorContext,
    ConnectorError,
    SourceItem,
    declared_reads,
    reads,
    skipped_counts,
    unreadable_dicts,
)
from engine.extract.attached import with_files_read
from engine.gate import reason_code
from engine.html_text import as_text
from engine.language_words import language_words
from engine.names import People
from engine.net import AnswerTooLarge
from engine.own_accounts import own_names
from engine.plain_errors import reason_of
from engine.sides import word
from engine.state_file import write_whole
from engine.storage import StoreError, WriteContext
from engine.triage import classify, classify_placed

#: The name a close carries when the change is to an older copy of a document's versions.
VERSION_RULE = "Older version"
_WATCHER = WriteContext(actor="watcher", trust="untrusted", op="watch.read")
_SORTER = WriteContext(actor="engine", trust="trusted", op="watch.sort")
#: Lines of unchanged text shown around each change in a diff.
CONTEXT_LINES = 2
#: What a request waits on when it has just been handed in and the assistant is about to take it.
STARTING = "With the assistant, starting now"

log = logging.getLogger(__name__)


@dataclass
class Result:
    source: str
    outcome: str
    new: list[str] = field(default_factory=list)  # request ids handed in
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    taken_in: list[str] = field(default_factory=list)  # request ids a first read took in quietly (not reported as new)
    problem: str | None = None
    note: str | None = None  # something to tell the person that isn't a problem with the source


#: Where an absence calendar's read keeps the names that matched nobody, in the read's saved state.
ABSENCE_NAMES = "absence_names"

#: What a read says when the same source is already being read.
ALREADY_READING = "Already reading this source"

_reading: dict[tuple[str, str], threading.Lock] = {}
_reading_guard = threading.Lock()


def _read_lock(ws: Any, source_id: str) -> threading.Lock:
    """The one lock for a source in a workspace, shared by every caller in this process."""
    with _reading_guard:
        return _reading.setdefault((str(ws.db_path), source_id), threading.Lock())


def connectors(store: Any) -> dict[str, Connector]:
    """Every connector this install has: the core's and running plugins'."""
    return {**CORE, **store.plugins.connectors()}


class AddonMissing(ConnectorError):
    """The connector a source names isn't running here. The detail says which add-on and what to do, so no other
    advice is added to it."""

    def __init__(self, detail: str) -> None:
        super().__init__("not_found", detail)
        self.kind = "addon"  # type: ignore[assignment]


def missing_connector(store: Any, cfg: Any, connector: str) -> str:
    """Why a source's connector isn't running, and what to do, in plain words: the add-on that provides it isn't
    installed, is turned off, or stopped; or this install has nothing by that name."""
    plugin = connector.split("/", 1)[0] if "/" in connector else ""
    if not plugin:
        return "this install has no way to read it any more. Pick how it is read again (Change, on Connections)"
    host = store.plugins
    status = getattr(host, "status", {}).get(plugin)
    if plugin not in getattr(host, "candidates", {}):
        return f'the add-on "{plugin}" that reads it isn\'t installed here. Install it again from Add-ons'
    if plugin not in cfg.workspace.plugins.enabled:
        return f'the add-on "{plugin}" that reads it is turned off. Turn it on in Add-ons'
    if status is not None and status.state == "disabled":
        return f'the add-on "{plugin}" that reads it stopped ({status.reason}). Add-ons says more'
    return (
        f'the add-on "{plugin}" doesn\'t read this kind of connection any more. '
        "Pick how it is read (Change, on Connections)"
    )


def last_run(store: Any, source: str) -> Any | None:
    runs = store.read().find("watch_run", {"source": source})
    return runs[-1] if runs else None


def problem_text(store: Any, source: str) -> str | None:
    """Why the latest try at a source failed and what to do about it, in plain words; None when it didn't fail."""
    last = last_run(store, source)
    if last is None or last.data["outcome"] != "failed":
        return None
    kind = last.data.get("error_kind") or ""
    return _problem(
        plain_what(kind, last.data.get("error"), bool(last.data.get("error_own"))),
        advice_for(kind, last.data.get("error_advice")),
    )


def last_read(store: Any, source: str) -> Any | None:
    """The latest run that actually read the source (not one that found no network or failed)."""
    runs = [r for r in store.read().find("watch_run", {"source": source}) if r.data["outcome"] in ("ok", "baseline")]
    return runs[-1] if runs else None


@dataclass(frozen=True)
class Unread:
    """A source that has been failing for longer than its usual gap: when it was last read (or first tried, when it
    never was), the kind of failure and what went wrong with what to do, in plain words."""

    since: str
    kind: str
    problem: str
    days: int = 0  # for old data: how many days old it is


#: The colors a calendar's mark can have, in the order the app gives them to calendars the person gave none.
CALENDAR_COLORS = ("blue", "teal", "green", "orange", "red", "pink", "purple", "gray")


def calendar_colors(cfg: Any, declared: Any) -> dict[str, str]:
    """The color of each calendar source's mark on the schedule, by source id: the one the person picked, else the first
    color of the list no calendar holds yet, so the first eight calendars never share one (after that the list starts
    over). A source that isn't a calendar has none."""
    from engine.connectors import reads

    calendars = [s for s in cfg.watch.sources if "calendar" in reads(s.connector, declared)]
    taken = [s.color for s in calendars if s.color]
    out: dict[str, str] = {}
    spare = [c for c in CALENDAR_COLORS if c not in taken]
    given = 0
    for source in calendars:
        if source.color:
            out[source.id] = source.color
            continue
        out[source.id] = spare[given] if given < len(spare) else CALENDAR_COLORS[given % len(CALENDAR_COLORS)]
        given += 1
    return out


def interval_minutes(store: Any, cfg: Any, source: Any) -> int:
    """How often a source is read, in minutes: its own interval when one was set by hand, else the mail or calendar
    interval the settings give, whatever add-on made the source. A source that reads neither uses the mail one."""
    if source.every_minutes:
        return int(source.every_minutes)
    kinds = reads(source.connector, declared_reads(connectors(store)))
    return int(cfg.watch.calendar_read_minutes if kinds == ["calendar"] else cfg.watch.mail_read_minutes)


def unread(store: Any, cfg: Any, source: Any, now: datetime) -> Unread | None:
    """Whether a source that is on has been failing for longer than `watch.unread_gap_factor` times its own read
    interval, counted from its first failed read in the current run of failures (so one failed read after a long quiet
    gap is not yet a failure). It says `since` the last good read (its first try when it never had one). A read that
    found no network or was throttled neither starts nor ends a failure, so a source that is only offline is never
    reported."""
    if not source.enabled:
        return None
    runs = store.read().find("watch_run", {"source": source.id})
    failing = next((r for r in reversed(runs) if r.data["outcome"] not in ("offline", "throttled")), None)
    if failing is None or failing.data["outcome"] != "failed":
        return None
    read = last_read(store, source.id)
    since = str((read or runs[0]).data["started_at"])
    began = failing
    for earlier in reversed(runs[: runs.index(failing)]):
        if earlier.data["outcome"] in ("offline", "throttled"):
            continue
        if earlier.data["outcome"] != "failed":
            break
        began = earlier
    if now - datetime.fromisoformat(str(began.data["started_at"])) <= timedelta(
        minutes=interval_minutes(store, cfg, source) * cfg.watch.unread_gap_factor
    ):
        return None
    kind = failing.data.get("error_kind") or ""
    problem = _problem(
        plain_what(kind, failing.data.get("error"), bool(failing.data.get("error_own"))),
        advice_for(kind, failing.data.get("error_advice")),
    )
    return Unread(since=since, kind=kind, problem=problem)


def stale_since(store: Any, cfg: Any, source: Any, now: datetime) -> str | None:
    """When a source that is on was last read, when that was more than `watch.stale_after_hours` ago, so a screen that
    would say nothing needs the person names it. None for a source that is off, one never read (it is not read yet, a
    state of its own) and one read within the time."""
    if not source.enabled:
        return None
    read = last_read(store, source.id)
    if read is None:
        return None
    since = str(read.data["started_at"])
    if now - datetime.fromisoformat(since) <= timedelta(hours=cfg.watch.stale_after_hours):
        return None
    return since


def _is_old(source: Any, generated_at: str | None, now: datetime) -> bool:
    """Whether the data a source says it was made at is older than its normal refresh (`data_fresh_hours`). A source
    that says no time, or one that can't be read, is not old: nothing is known."""
    if not generated_at:
        return False
    try:
        made = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if made.tzinfo is None:
        return False
    return now - made > timedelta(hours=source.data_fresh_hours)


@dataclass(frozen=True)
class OldData:
    """A source whose latest read served data older than its normal refresh: when the data was made and how many whole
    days old it is now."""

    generated_at: str
    days: int


def old_data(store: Any, cfg: Any, source: Any, now: datetime) -> OldData | None:
    """The old-data state of a source that is on: its latest read served data stamped older than `data_fresh_hours`,
    and it still is. None for a source that is off, one never read, one whose data says no time, and one that is fresh.
    A source that is failing is the unread line's, not this one's."""
    if not source.enabled:
        return None
    read = last_read(store, source.id)
    if read is None or not read.data.get("old_data") or not read.data.get("generated_at"):
        return None
    made = str(read.data["generated_at"])
    if not _is_old(source, made, now):
        return None
    return OldData(made, max(1, (now - datetime.fromisoformat(made)).days))


def due(store: Any, cfg: Any, now: datetime) -> list[str]:
    """Sources that are on and whose time has come."""
    found = []
    for source in cfg.watch.sources:
        if not source.enabled:
            continue
        last = last_run(store, source.id)
        started = datetime.fromisoformat(str(last.data["started_at"])) if last else None
        retry_at = last.data.get("retry_at") if last else None
        if retry_at:
            # The service asked to wait: the source is read again when that time comes, not a whole interval later.
            if now < datetime.fromisoformat(str(retry_at)):
                continue
        elif started is not None and now - started < timedelta(minutes=interval_minutes(store, cfg, source)):
            continue
        found.append(source.id)
    return found


def next_retry_in(store: Any, cfg: Any, now: datetime) -> float | None:
    """Seconds until the earliest wait a service asked for runs out on a source that is on, 0 when one has run out
    already and the source hasn't been read since; None when no source is waiting."""
    soonest: float | None = None
    for source in cfg.watch.sources:
        if not source.enabled:
            continue
        last = last_run(store, source.id)
        retry_at = last.data.get("retry_at") if last else None
        if not retry_at:
            continue
        left = max(0.0, (datetime.fromisoformat(str(retry_at)) - now).total_seconds())
        soonest = left if soonest is None else min(soonest, left)
    return soonest


def failures_in_a_row(store: Any, source: str) -> int:
    count = 0
    for run in reversed(store.read().find("watch_run", {"source": source})):
        if run.data["outcome"] in ("offline", "throttled"):
            continue
        if run.data["outcome"] != "failed":
            break
        count += 1
    return count


def refresh(ws: Any, store: Any, cfg: Any, source_id: str, now: datetime | None = None, router: Any = None) -> Result:
    """Read one source now, compare and hand in what changed. Returns what happened. A source is never read twice at
    the same moment: when another read of it is under way this one does nothing and says so (outcome "busy"). The
    router makes the assistant's sorting run for mail the rules can't place; left out, one is made when it is needed."""
    if not any(s.id == source_id for s in cfg.watch.sources):
        raise StoreError(f"there is no source {source_id}")
    lock = _read_lock(ws, source_id)
    if not lock.acquire(blocking=False):
        return Result(source_id, "busy", note=ALREADY_READING)
    try:
        result = _refresh(ws, store, cfg, source_id, now, router)
    finally:
        lock.release()
    _follow_account_answer(ws, store, cfg, source_id, now, router)
    return result


def _follow_account_answer(ws: Any, store: Any, cfg: Any, source_id: str, now: Any, router: Any) -> None:
    """After a source's first read, give it the answer already given to the full-read question for its account (outside
    the read lock, which the read of older mail takes). A failure here never fails the read."""
    from engine import source_intake

    try:
        source_intake.follow_account_answer(ws, store, cfg, source_id, now, router)
    except Exception:  # the source keeps its open question, which the person can still answer
        log.exception("applying the account's full-read answer to %s failed", source_id)


def _refresh(ws: Any, store: Any, cfg: Any, source_id: str, now: datetime | None, router: Any = None) -> Result:
    now = now or datetime.now(UTC)
    clock = time.monotonic()
    source = next((s for s in cfg.watch.sources if s.id == source_id), None)
    if source is None:
        raise StoreError(f"there is no source {source_id}")
    worked = [
        r for r in store.read().find("watch_run", {"source": source.id}) if r.data["outcome"] in ("ok", "baseline")
    ]
    # A read that failed keeps nothing: the next one starts from the last read that worked.
    state = dict(worked[-1].data.get("state") or {}) if worked else {}
    connector = connectors(store).get(source.connector)
    try:
        if connector is None:
            raise AddonMissing(missing_connector(store, cfg, source.connector))
        try:
            settings = connector.settings.model_validate(source.settings)
        except ValidationError as err:
            first = err.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "settings"
            raise AddonMissing(
                f"its settings don't fit: {where}: {reason_of(first)}. {advice_for('no_access')}"
            ) from None
        poll = _poll(store, connector, settings, state, ws, cfg, now, source.account)
    except ConnectorError as err:
        return _failed_read(store, cfg, source, err, now, clock)
    if source.holds == "absence":
        return _read_absence(store, cfg, source, poll, settings, now, clock)
    if _served_older_copy(worked, poll.generated_at):
        return _record_older_copy(store, source, worked, now, clock)
    read_before = any(
        r.data["outcome"] in ("ok", "baseline") for r in store.read().find("watch_run", {"source": source.id})
    )
    old = _is_old(source, poll.generated_at, now)
    # The first fresh read after one that served old data brings in what it missed together.
    catching_up = bool(worked) and bool(worked[-1].data.get("old_data")) and not old
    from engine import capture

    # A capture folder holds the person's own words: everything in it is handed in, the first read included.
    own = capture.is_capture(source)
    taking_in = not read_before and not own and source.first_run == "intake"
    baseline = not read_before and not own and source.first_run in ("baseline", "recent", "intake")
    recent = timedelta(hours=source.first_run_hours) if baseline and source.first_run == "recent" else None
    mine = capture.own_mail_keys(cfg, source, poll.items)
    if own:
        result = capture.compare(ws, store, cfg, source, poll, now)
    elif mine:
        # Mail the person put in a capture folder or sent to a capture address from their own address is their own
        # words; everything else the source read goes through the ordinary comparison, as outside content.
        rest = replace(poll, items=[i for i in poll.items if i.key not in mine])
        result = _compare(ws, store, cfg, source, rest, now, baseline, recent, router, catching_up)
        taken = capture.compare(
            ws,
            store,
            cfg,
            source,
            replace(poll, items=[i for i in poll.items if i.key in mine], complete=poll.complete),
            now,
            everything={i.key for i in poll.items},
        )
        result.new.extend(taken.new)
        result.changed.extend(taken.changed)
    else:
        result = _compare(ws, store, cfg, source, poll, now, baseline, recent, router, catching_up)
    from engine import source_entries, source_intake

    source_entries.keep(store, cfg, source, poll.items, now)

    back_to = (
        source_intake.looked_back_to(source, poll.items, now, poll.capped or bool(poll.state.get("capped")))
        if taking_in
        else None
    )
    _record(
        store,
        source.id,
        now,
        clock,
        "baseline" if baseline else "ok",
        new=len(result.new),
        changed=len(result.changed),
        removed=len(result.removed),
        unsorted=result.note,
        unreadable=unreadable_dicts(poll.unreadable),
        skipped=skipped_counts(poll.unreadable),
        state=poll.state,
        generated_at=poll.generated_at,
        old_data=old,
        looked_back_to=back_to.isoformat() if back_to else None,
        asks_full_read=bool(back_to),
    )
    if taking_in:
        result.taken_in = source_intake.take_in(ws, store, cfg, source, now, router, back_to)
    _close_question(store, source.id)
    _tell_unreadable(store, cfg, source, poll.unreadable)
    if baseline:
        # A mail account's first read is followed by a sample of its newest headers (no assistant work, nothing handed
        # in); the rest of the year is read later in the account's lane.
        from engine import mail_headers

        mail_headers.read_after_first(ws, store, cfg, source, now, clock, back_to)
    _after_mail(ws, store, cfg, now)
    result.outcome = "baseline" if baseline else "ok"
    return result


def _moment(value: Any) -> datetime | None:
    """A time a source or a saved read gave, as an aware time; none when it says none or can't be read."""
    if isinstance(value, datetime):
        made = value
    else:
        try:
            made = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return made if made.tzinfo is not None else None


def _newest_copy(worked: list[Any]) -> datetime | None:
    """The newest time a source's own data was made, over the reads that worked."""
    seen = [m for r in worked if (m := _moment(r.data.get("generated_at"))) is not None]
    return max(seen) if seen else None


def _served_older_copy(worked: list[Any], generated_at: str | None) -> bool:
    """Whether the source says its data was made before the newest copy it has served: a restore or a cache. A source
    that says no time is read at the time of the read, which never goes back."""
    made, newest = _moment(generated_at), _newest_copy(worked)
    return made is not None and newest is not None and made < newest


def _record_older_copy(store: Any, source: Any, worked: list[Any], now: datetime, clock: float) -> Result:
    """Keep the read as one that compared nothing: the newest copy's state and time stay as they were, so the older copy
    is never compared, stored or filed, and the next read of the newest copy compares with what it did before."""
    last = worked[-1].data
    newest = _newest_copy(worked)
    _record(
        store,
        source.id,
        now,
        clock,
        "ok",
        older_copy=True,
        state=dict(last.get("state") or {}),
        generated_at=newest.isoformat() if newest else None,
        old_data=bool(last.get("old_data")),
    )
    return Result(source.id, "ok", note=word(None, "read.older_copy"))


def refusal(err: ConnectorError) -> dict[str, Any]:
    """What a refusing answer is kept as: its status code and its reason, the error's kind and the add-on's short
    reason code if it gave one, never the service's own words."""
    return {"refused_status": err.status, "refused_reason": reason_code(err)}


def _failed_read(store: Any, cfg: Any, source: Any, err: ConnectorError, now: datetime, clock: float) -> Result:
    """Record a read that a connector refused, as the person is told of it: the kind of failure, the wait a throttled
    read asked for, and the problem in words (one question to the person at the configured count of failures)."""
    err.advice_key = _sign_in_advice(store, source.connector, err.advice_key)
    if isinstance(err, AnswerTooLarge):
        # An answer over the limit says so in the app's own words, never the service's text or the size.
        err.detail = word(None, "read.failed.too_large")
    outcome = {"offline": "offline", "throttled": "throttled"}.get(err.kind, "failed")
    wait = err.retry_after if err.retry_after is not None else interval_minutes(store, cfg, source) * 60
    refused = refusal(err)
    log.info(
        "read of %s refused: %s, status %s, wait %s",
        source.id,
        refused["refused_reason"],
        refused["refused_status"],
        err.retry_after,
    )
    _record(
        store,
        source.id,
        now,
        clock,
        outcome,
        error_kind=err.kind if outcome == "failed" else None,
        error=err.detail or None,
        error_own=_own_words(source, err),
        error_advice=err.advice_key if outcome == "failed" else None,
        **refused,
        **({"wait_seconds": err.retry_after} if outcome == "throttled" and err.retry_after is not None else {}),
        **({"retry_at": (now + timedelta(seconds=wait)).isoformat()} if outcome == "throttled" else {}),
    )
    problem = None
    if outcome == "failed":
        problem = _maybe_ask(store, cfg, source, err)
    return Result(source.id, outcome, problem=problem)


def _read_absence(store: Any, cfg: Any, source: Any, poll: Any, settings: Any, now: datetime, clock: float) -> Result:
    """Read a calendar that holds who is away (design 5.1): its entries become days away by rules, never calendar
    entries, meetings or work handed to the assistant. The names that matched nobody are kept with the read, for the
    source's row."""
    from engine import absence

    report = absence.read(store, cfg, source, poll, settings, now)
    _record(
        store,
        source.id,
        now,
        clock,
        "ok",
        new=0,
        changed=report.written,
        removed=0,
        state={**poll.state, ABSENCE_NAMES: report.names},
    )
    _close_question(store, source.id)
    return Result(source.id, "ok")


def unmatched_names(store: Any, source: str) -> list[str]:
    """The names an absence calendar's last read gave that matched no known person."""
    last = last_read(store, source)
    return list((last.data.get("state") or {}).get(ABSENCE_NAMES) or []) if last is not None else []


def _after_mail(ws: Any, store: Any, cfg: Any, now: datetime) -> None:
    """After mail is taken in, use what the person's own sent mail shows (design 6.35): note on each sent message which
    open replies owed it may answer, for the assistant to read, and match each sent message to the message they copied,
    recording what they changed before sending. The rules find candidates and matches, never decide that a reply
    answers, and a failure here never fails the read."""
    from engine import reply_lines, sent_version

    with contextlib.suppress(StoreError):
        reply_lines.mark_candidates(ws, store, cfg)
    with contextlib.suppress(StoreError):
        sent_version.match_sent(ws, store, cfg, now)


def _another_message(before: Any, item: SourceItem) -> bool:
    """Whether a saved mail snapshot is a different message from this item with the same key: a message's date and its
    sender's address never change (a display name can, so it isn't compared), so a different one of either, when both
    are known, is another message. A snapshot whose content was deleted keeps only a marker, so it is never compared."""
    from email.utils import parseaddr

    saved = before.data.get("message")
    if saved is None or item.message is None or before.data.get("deleted"):
        return False
    if saved.get("received") and item.message.received and saved["received"] != item.message.received:
        return True
    was, now = parseaddr(saved.get("sender") or "")[1].lower(), parseaddr(item.message.sender or "")[1].lower()
    return bool(was and now and was != now)


def _own_key(seen: dict[str, Any], item: SourceItem) -> SourceItem:
    """The item under the key that is its own: its key when nothing saved under it is another message, else the key with
    `#2`, `#3` and so on after it, the first of those that holds nothing, or that holds this very message. Anyone on a
    thread can write a Message-ID they have seen, so the second message to carry one never replaces the first."""
    if item.message is None:
        return item
    key, number = item.key, 1
    while (before := seen.get(key)) is not None and _another_message(before, item):
        number += 1
        key = f"{item.key}#{number}"
    return item if key == item.key else replace(item, key=key)


def _poll(
    store: Any,
    connector: Connector,
    settings: Any,
    state: dict[str, Any],
    ws: Any,
    cfg: Any,
    now: datetime,
    account: str | None = None,
) -> Any:
    context = ConnectorContext(
        workspace_root=ws.root,
        now=now,
        timezone=cfg.workspace.user.timezone,
        hosted=cfg.server.mode == "hosted",
    )
    if "/" not in connector.name:
        return connector.poll(settings, state, context)
    return store.plugins.poll_connector(connector, settings, state, context, account)


def is_recent(details: dict[str, Any], changed_at: str | None, now: datetime, window: timedelta) -> bool:
    """Whether an item belongs to the recent past or near future: a message received within the window, an event
    starting within it (before or after now), or else an item changed within it. An item with no time isn't."""
    from engine.connectors import moment

    message, event = details.get("message") or {}, details.get("event") or {}
    try:
        if message.get("received"):
            return now - window <= moment(message["received"]) <= now + timedelta(minutes=5)
        if event.get("start"):
            start = moment(event["start"], all_day=bool(event.get("all_day")))
            if not isinstance(start, datetime):
                start = datetime(start.year, start.month, start.day, tzinfo=now.tzinfo)
            return now - window <= start <= now + window
        if changed_at:
            return now - window <= moment(changed_at) <= now + timedelta(minutes=5)
    except (ValueError, TypeError):
        return False
    return False


@dataclass
class _Entry:
    """One item of a read that is new or changed: what the read found, and how the rules placed it."""

    item: SourceItem
    digest: str
    before: Any
    details: dict[str, Any]
    change: str
    old: str | None
    closed: dict[str, str] | None
    handed: bool  # it is handed in now, not only noted
    replaces: str | None = None  # for the current copy of a document's versions: the version it replaces
    personal: bool = False  # a rule says the mail is personal: handed in and filed under the Personal project


def _own_mail_ids(store: Any) -> set[str]:
    """The Message-IDs of the notices and reminders the app itself sent to the person by mail, as the channel recorded
    them on each sent act, so one that comes back into a read inbox is known."""
    return {
        str(a.data["service_id"])
        for a in store.read().list("act")
        if a.data.get("made_by") in ("notices", "reminders") and a.data.get("service_id")
    }


def _held_by_twins(store: Any, cfg: Any, source: Any) -> set[str]:
    """The keys of the items another source of the same add-on connector and account already holds. A message is named
    by the account's own id for it, so two sources reading folders that both list it (or the same folder twice) see one
    message, which is taken in once: by whichever source read it first."""
    if "/" not in source.connector:
        return set()
    twins = [
        s.id
        for s in cfg.watch.sources
        if s.id != source.id and s.connector == source.connector and s.account == source.account
    ]
    return {snap.data["key"] for sid in twins for snap in store.read().find("snapshot", {"source": sid})}


def _held_message_ids(store: Any, source: Any) -> set[str]:
    """The Message-IDs of the messages another source already holds, whatever its account: a message sent to several
    mailboxes of one person (or sent by them to themselves) is held by each under that mailbox's own key but with one
    Message-ID, and is one message, taken in once by whichever source read it first."""
    return {
        str(snap.data["message"]["message_id"])
        for snap in store.read().list("snapshot")
        if snap.data.get("source") != source.id and (snap.data.get("message") or {}).get("message_id")
    }


class MessageIndex:
    """Which snapshots hold each Message-ID, and which items have been handed in, read once for a whole pass over a
    source's items so each is checked without going over every snapshot again."""

    def __init__(self, view: Any) -> None:
        self.handed = {
            ((s.data.get("watched") or {}).get("source"), (s.data.get("watched") or {}).get("key"))
            for s in view.list("source")
            if (s.data.get("watched") or {}).get("key")
        }
        self.holders: dict[str, list[Any]] = {}
        for snap in view.list("snapshot"):
            message_id = (snap.data.get("message") or {}).get("message_id")
            if message_id and not snap.data.get("gone") and not snap.data.get("deleted"):
                self.holders.setdefault(str(message_id), []).append(snap)

    def taken_elsewhere(self, snap: Any) -> bool:
        """Whether the message a snapshot holds is already another source's to take in: a message sent to several
        mailboxes of one person (or by them to themselves) is held by each under that mailbox's own key with one
        Message-ID, and is one message, handed in once by the source that already handed it in, or else by whichever
        read it first (the earlier snapshot)."""
        message_id = (snap.data.get("message") or {}).get("message_id")
        if not message_id:
            return False

        def order(record_id: str) -> int:
            tail = record_id.rpartition("-")[2]
            return int(tail) if tail.isdigit() else 0

        for other in self.holders.get(str(message_id), []):
            if other.id == snap.id or other.data["source"] == snap.data["source"]:
                continue
            if (other.data["source"], other.data["key"]) in self.handed or order(other.id) < order(snap.id):
                return True
        return False


def _burst_keys(cfg: Any, source: Any, entries: list[_Entry], catching_up: bool = False) -> set[str]:
    """The keys of the items one read hands in as a burst (design 6.2): a page, feed or tracker (never mail, a calendar
    or a folder, whose items stay one input each) that hands in more than `watch.burst_items` open items at once. An
    item a rule closes makes no run and isn't counted. Empty when the read is not a burst. The read that brings back
    fresh data after old data (`catching_up`) also files a calendar's events this way, so what was missed is one
    catch-up item, not one input each."""
    if source.connector in versions.FOLDER_CONNECTORS or source.connector == "capture":
        return set()
    open_items = [
        e
        for e in entries
        if e.handed
        and e.closed is None
        and e.item.message is None
        and (e.item.event is None or catching_up)
        and e.replaces is None
    ]
    return {e.item.key for e in open_items} if len(open_items) > cfg.watch.burst_items else set()


def _hand_in_burst(
    ws: Any,
    store: Any,
    cfg: Any,
    source: Any,
    burst: list[_Entry],
    now: datetime,
    home: str | None,
    personal_keys: set[str],
    save: Any,
    catching_up: bool = False,
) -> list[str]:
    """File a burst as one input for each project (design 6.2): the source's own project when it has one, else the
    project the rules place the item under (the Personal project for an item a rule says is personal), else one input
    for the items nobody placed. An input's text holds each item as its own block, with its watch and item names, so a
    claim quotes the block it came from; it is one source record, so one input per AI call holds. Returns the new
    requests' ids, none when there was no burst. `save` writes an item's snapshot inside the same transaction as the
    input it joins, so a failure leaves none of them marked as seen."""
    groups: dict[str | None, list[_Entry]] = {}
    for entry in burst:
        placed = source.project or (home if home and (entry.personal or entry.item.key in personal_keys) else None)
        groups.setdefault(placed, []).append(entry)
    made = []
    for placed, entries in groups.items():
        blocks = []
        for number, entry in enumerate(entries, 1):
            name = " ".join(entry.item.title.split())[:200]
            head = f'Item {number} of {len(entries)} (watch: {source.id}; item: "{name}")'
            blocks.append(f"{head}\n\n{_input_text(source, entry.item, entry.change, entry.old, entry.replaces)}")
        what = "missed changes" if catching_up else "changes"
        title = f"{len(entries)} {what} in {source.label or source.id}"[:120]
        whole = SourceItem(f"burst:{placed or ''}", title, "", author=None)
        extra = {"project": placed} if placed and not source.project else None
        with store.transaction() as tx:
            for entry in entries:
                save(tx, entry)
            made.append(
                _hand_in(
                    ws,
                    store,
                    tx,
                    cfg,
                    source,
                    whole,
                    "new",
                    "\n\n---\n\n".join(blocks),
                    now,
                    None,
                    extra=extra,
                    burst=True,
                )
            )
    return made


def _compare(
    ws: Any,
    store: Any,
    cfg: Any,
    source: Any,
    poll: Any,
    now: datetime,
    baseline: bool,
    recent: timedelta | None = None,
    router: Any = None,
    catching_up: bool = False,
) -> Result:
    from engine import capture

    result = Result(source.id, "ok")
    # Mail handed in as the person's own capture is not this comparison's: it isn't outside content to compare again.
    seen = {
        s.data["key"]: s
        for s in store.read().find("snapshot", {"source": source.id})
        if not s.data["gone"] and s.data.get("closed_by") != capture.CAPTURED
    }
    listed = set()
    entries: list[_Entry] = []
    own_ids: set[str] | None = None
    unplaced: dict[str, dict[str, Any]] = {}
    held_by_twins = _held_by_twins(store, cfg, source)
    held_ids = _held_message_ids(store, source)
    plain = entry_rules.Plain(store.read(), cfg, source.id)
    folder = source.connector in versions.FOLDER_CONNECTORS and cfg.watch.versions.enabled
    asking = People(store, cfg).pm if folder else None
    families = None
    if folder:
        # A choice names a file by the hash of its text: one edited in place since keeps its choices, for this read
        # and, written back, for the next.
        found = [versions.Listed(i.key, i.changed_at, versions.digest_of(i.text)) for i in poll.items]
        followed = {
            seen[i.key].data["content_hash"]: i.digest
            for i in found
            if i.key in seen and seen[i.key].data["content_hash"] != i.digest
        }
        version_choices.follow_edits(ws, cfg, store, source.id, followed)
        families = versions.Families(
            found,
            cfg.watch.versions,
            source.id,
            give_up=version_choices.given_up(store.read(), source.id),
            ask=asking is not None,
            followed=followed,
        )
    for listed_item in poll.items:
        # A message whose Message-ID a saved, different message already has is its own item, never that one's change.
        polled = _own_key(seen, listed_item)
        listed.add(polled.key)
        # Files an item carries are read as text first, so the item is compared and handed in with their words.
        item = with_files_read(
            ws, store, cfg, polled, source.label or source.id, keep_at_level=data_level_of(cfg, source)
        )
        digest = _keep_text(ws, item.text)
        before = seen.get(item.key)
        if before is not None and before.data.get("deleted"):
            continue  # the person had its content deleted; only its marker is kept, so it isn't handed in again
        details = _details(item)
        if before is not None and _same_words(ws, before, item.text, digest):
            # Only what it is changed (a message was opened, say): kept for Today, nothing to read again. The text
            # saved before markup was turned into text is the same words, so its hash moves to the new one.
            kept_now = {**details, "content_hash": digest}
            if before.data["content_hash"] != digest:
                _keep_text(ws, item.text)  # the hash moves to text that must be there for the next comparison
            if any(before.data.get(k) != v for k, v in kept_now.items()):
                with store.transaction() as tx:
                    tx.update("snapshot", before.id, kept_now, _WATCHER, read_version=before.version)
            continue
        change = "new" if before is None else "changed"
        old = _read_text(ws, before.data["content_hash"]) if before is not None else None
        facts = _change(cfg, source, item, change, old)
        closed, kept, personal = classify_placed(store, cfg, facts)
        older = families.older_than_current(item.key, item.changed_at) if families else None
        if older and closed is None:
            closed = {"rule": VERSION_RULE, "reason": older}
        replaces = families.replaces(item.key) if families and not older else None
        handed = not baseline or (recent is not None and is_recent(details, item.changed_at, now, recent))
        if handed and before is None and item.message is not None and item.key in held_by_twins:
            handed = False  # another source of this account took this message in already: one message, one item
        if handed and before is None and item.message is not None and item.message.message_id in held_ids:
            handed = False  # another mailbox took the same message in already (its Message-ID): one message, one item
        if handed and plain.of(item):
            handed = False  # a plain calendar entry is kept by rule, with no run and no line (design 6.32)
        if handed and item.message is not None and item.message.message_id:
            if own_ids is None:
                own_ids = _own_mail_ids(store)
            if item.message.message_id in own_ids:
                handed = False  # a notice or reminder the app sent to the person comes back: nothing new (design 7.19)
        if closed is None and not kept:
            closed = _carried_sorting(before)
        if handed and closed is None and not kept and before is None and item.message is not None:
            unplaced[item.key] = facts
        entries.append(_Entry(item, digest, before, details, change, old, closed, handed, replaces, personal))
    marks, personal_keys, result.note, unsorted_keys, kinds = _assistant_sorted(
        ws, store, cfg, source, router, unplaced
    )
    home = _personal_home(store, cfg)
    grouped = _burst_keys(cfg, source, entries, catching_up)
    burst: list[_Entry] = []

    def save(tx: Any, entry: _Entry) -> None:
        """The item's snapshot, so the next read compares with what this one found."""
        item, before = entry.item, entry.before
        closed = entry.closed or marks.get(item.key)
        data = {
            "source": source.id,
            "key": item.key,
            "title": item.title,
            "content_hash": entry.digest,
            "author": item.author,
            "seen_at": now.isoformat(),
            **entry.details,
            "closed_by": closed["rule"] if closed and not closed.get("section") else None,
            "set_aside": _set_aside_of(closed) or _kept_set_aside(before),
        }
        if before is None:
            tx.create("snapshot", data, _WATCHER)
        else:
            tx.update("snapshot", before.id, data, _WATCHER, read_version=before.version)

    for entry in entries:
        item, closed = entry.item, entry.closed or marks.get(entry.item.key)
        if entry.handed and item.key in grouped:
            burst.append(entry)  # saved with its input, in one transaction, so a failure never marks it seen unread
            continue
        with store.transaction() as tx:
            save(tx, entry)
            if not entry.handed:
                continue
            if families and asking and (unclear := families.unclear(item.key)):
                version_choices.ask(tx, source.id, asking, *unclear)
            text = _input_text(source, item, entry.change, entry.old, entry.replaces)
            filed = {"project": home} if home and (entry.personal or item.key in personal_keys) else None
            if item.key in unsorted_keys and not closed:
                filed = {**(filed or {}), "sort_pending": True}
            if item.key in kinds:
                filed = {**(filed or {}), "mail_kind": kinds[item.key]}
            request = _hand_in(ws, store, tx, cfg, source, item, entry.change, text, now, closed, extra=filed)
        (result.new if entry.change == "new" else result.changed).append(request)
    result.new.extend(_hand_in_burst(ws, store, cfg, source, burst, now, home, personal_keys, save, catching_up))
    gone_keys = [k for k in seen if k not in listed] if poll.complete else [k for k in poll.removed if k in seen]
    for key in gone_keys:
        snapshot = seen[key]
        with store.transaction() as tx:
            tx.update("snapshot", snapshot.id, {"gone": True}, _WATCHER, read_version=snapshot.version)
            if baseline or not source.report_removed or snapshot.data.get("message") is not None:
                # a message leaving its folder (filed, archived, deleted) is routine, never a change to hand in
                continue
            gone = SourceItem(key, snapshot.data["title"], "", author=None)
            text = f"{snapshot.data['title']} is no longer in {source.label or source.id}."
            facts = _change(cfg, source, gone, "removed", _read_text(ws, snapshot.data["content_hash"]))
            closed = classify(store, cfg, facts)[0]
            older = families.older_than_current(key, snapshot.data.get("changed_at"), gone=True) if families else None
            if older and closed is None:
                closed = {"rule": VERSION_RULE, "reason": older}
            result.removed.append(_hand_in(ws, store, tx, cfg, source, gone, "removed", text, now, closed))
    return result


def _assistant_sorted(
    ws: Any, store: Any, cfg: Any, source: Any, router: Any, unplaced: dict[str, dict[str, Any]], go: bool = False
) -> tuple[dict[str, dict[str, str]], set[str], str | None, set[str], dict[str, str]]:
    """The assistant's sorting (design 6.5, step 3) of the mail the rules couldn't place, as {item key: facts}: one
    run per batch of headers, never the text. Returns, by item key, the set-aside match of each message it set aside,
    the keys it answered personal (handed in and filed under the Personal project, never set aside), a note when
    some mail wasn't sorted by it, the keys of the mail the run couldn't be made for (handed in, waiting for the
    sorting before any other run), and the kind the run gave each message it answered (kept on its request)."""
    from engine import mail_sorting
    from engine.set_aside import SECTION_WORDS

    if cfg.watch.sorting != "ai" or not unplaced:
        return {}, set(), None, set(), {}
    sorted_ = mail_sorting.sort(
        ws,
        store,
        cfg,
        router,
        [mail_sorting.header_of(key, facts, cfg.watch.mail_kinds, cfg) for key, facts in unplaced.items()],
        data_level_of(cfg, source),
        go,
    )
    marks = {
        key: {
            "rule": mail_sorting.RULE,
            "reason": f"the assistant sorted it as {SECTION_WORDS[section]}",
            "section": section,
            "by": "assistant",
        }
        for key, section in sorted_.sections.items()
    }
    return marks, sorted_.personal, sorted_.note, sorted_.unsorted, sorted_.kinds


def _personal_home(store: Any, cfg: Any) -> str | None:
    """The Personal project mail that is personal is filed under, when the workspace has one."""
    from engine import sides

    return sides.personal_project(store.read(), cfg)


def _awaiting_sorting(
    ws: Any,
    store: Any,
    cfg: Any,
    only: str | None = None,
    pending_only: bool = False,
    requests: set[str] | None = None,
) -> dict[str, list[tuple[Any, Any, SourceItem, dict[str, Any]]]]:
    """The mail the first go's sorting covers, by source id: each as (request, snapshot, item, facts). Mail handed in
    unsorted while the go was pending, still waiting for it or queued, whose message was never sorted. Mail the person
    pulled back as work, mail a rule now places or keeps, and changed messages are left out. Mail a new source's
    intake holds for its own go is covered too; `only` limits it to one source. `pending_only` keeps just the requests
    still marked `sort_pending`: mail the sorting couldn't be run for when it was handed in."""
    from engine import source_intake
    from engine.connectors import EventDetails
    from engine.dispatcher import waits_on_first_go

    if cfg.watch.sorting != "ai":
        return {}
    view = store.read()
    pulled = {ref for s in view.list("signal") if s.data["kind"] == "pulled_back" for ref in s.data.get("refs", [])}
    snaps = {(s.data["source"], s.data["key"]): s for s in view.list("snapshot")}
    sources = {s.id: s for s in cfg.watch.sources}
    waiting: dict[str, list[tuple[Any, Any, SourceItem, dict[str, Any]]]] = {}
    for req in view.list("request"):
        data = req.data
        if data["task"] != "notes" or data["origin"] != "input" or not data.get("source") or req.id in pulled:
            continue
        if data.get("set_aside") or data.get("auto_closed") or data.get("folded_into") or data.get("dismissed"):
            continue
        if pending_only and not data.get("sort_pending"):
            continue
        if requests is not None and req.id not in requests:
            continue
        if not (data["state"] == "queued" or waits_on_first_go(data) or source_intake.waits_on_go(data)):
            continue
        record = view.get("source", data["source"])
        watched = (record.data.get("watched") if record else None) or {}
        snap = snaps.get((watched.get("source"), watched.get("key")))
        source = sources.get(watched.get("source", ""))
        if watched.get("change") != "new" or snap is None or source is None or (only and source.id != only):
            continue
        sd = snap.data
        if not sd.get("message") or sd.get("set_aside") or sd.get("gone") or sd.get("deleted"):
            continue
        item = SourceItem(
            sd["key"],
            sd["title"],
            _read_text(ws, sd["content_hash"]),
            author=sd.get("author"),
            changed_at=sd.get("changed_at"),
            link=sd.get("link"),
            event=EventDetails.from_dict(sd["event"]) if sd.get("event") else None,
            message=_message_of(sd.get("message")),
        )
        facts = _change(cfg, source, item, "new", None)
        closed, kept = classify(store, cfg, facts)
        if closed is None and not kept:
            waiting.setdefault(source.id, []).append((req, snap, item, facts))
    return waiting


def awaiting_sorting_ids(ws: Any, store: Any, cfg: Any, only: str | None = None) -> set[str]:
    """The requests whose mail a go's sorting covers (never sorted, still waiting or queued); of one source with
    `only`. A go marks them `sort_pending`, and the worker sorts them before any of them runs: nothing here asks the
    assistant."""
    return {req.id for found in _awaiting_sorting(ws, store, cfg, only).values() for req, _, _, _ in found}


def first_go_sorting(
    ws: Any, store: Any, cfg: Any, router: Any = None, only: str | None = None
) -> tuple[int, float | None, int]:
    """What the first go's sorting run adds to the spend: how many runs it makes, what the runs that have a price cost
    together (None when none has one) and how many have no price. Nothing when no mail waits for the sorting.
    `only` limits it to the mail of one source (a new source's intake). The cost is the most: every run at the full
    price (`first_go_sorting_range` also gives the likely price)."""
    runs, _likely, at_most, unpriced = first_go_sorting_range(ws, store, cfg, router, only)
    return runs, at_most, unpriced


def first_go_sorting_range(
    ws: Any, store: Any, cfg: Any, router: Any = None, only: str | None = None
) -> tuple[int, float | None, float | None, int]:
    """The first go's sorting as `first_go_sorting` counts it, in two figures: (runs, likely, at most, runs with no
    price). The likely price has the runs after the first charged with the packet's stable part at the account's cached
    price; the most has every run at the full price. Both None when no run has a price."""
    from engine import mail_sorting

    found = _awaiting_sorting(ws, store, cfg, only)
    if not found:
        return 0, None, None, 0
    if router is None:
        from engine.ai.router import Router

        router = Router(cfg, store, env=os.environ)
    sources = {s.id: s for s in cfg.watch.sources}
    runs, likely, at_most, unpriced = 0, 0.0, 0.0, 0
    for source_id, items in found.items():
        headers = [mail_sorting.header_of(item.key, facts, cfg.watch.mail_kinds, cfg) for _, _, item, facts in items]
        level = data_level_of(cfg, sources[source_id])
        soon, most, missing = mail_sorting.estimate_range(ws, cfg, router, headers, level, store.read())
        runs += -(-len(headers) // cfg.watch.sorting_batch)
        likely += soon
        at_most += most
        unpriced += missing
    priced = runs > unpriced
    return runs, (likely if priced else None), (at_most if priced else None), unpriced


def sort_before_first_go(
    ws: Any,
    store: Any,
    cfg: Any,
    router: Any = None,
    now: datetime | None = None,
    only: str | None = None,
    go: bool = True,
    pending_only: bool = False,
    requests: set[str] | None = None,
) -> int:
    """The person's first go covers the sorting of the mail that was handed in unsorted while it was pending: the
    mail requests still waiting for the go (or queued) whose message was never sorted go through the sorting run first,
    in the usual batches. Those it sets aside are closed as set aside, with the snapshot marked, and don't run; the
    rest are left for the go to start. Mail the person pulled back as work, mail a rule now places or keeps, and
    changed messages are left alone. Returns how many were set aside. Call it before the go is granted. `only`
    limits it to one source's mail (a new source's intake); `go` is False when nobody has given a go, so the
    sorting keeps the checks that wait for one. `pending_only` sorts just the mail whose requests are marked
    `sort_pending` (the worker's sorting before any other run); every request the sorting answers loses the mark, and
    one it couldn't be run for keeps it. Marked mail whose request the person's go already approved is sorted under
    that go, apart from marked mail nobody gave a go for. `requests` limits the sorting to those requests (a batch of
    the worker's pass), and the mark is cleared only on them."""
    waiting = _awaiting_sorting(ws, store, cfg, only, pending_only, requests)
    sources = {s.id: s for s in cfg.watch.sources}
    set_aside = 0
    still_waiting: set[str] = set()
    groups: list[tuple[str, list[tuple[Any, Any, SourceItem, dict[str, Any]]], bool]] = []
    for source_id, every in waiting.items():
        granted = [f for f in every if pending_only and not go and f[0].data.get("approval") == "granted"]
        rest = [f for f in every if f not in granted]
        groups += [(source_id, part, part_go) for part, part_go in ((granted, True), (rest, go)) if part]
    for source_id, found, with_go in groups:
        marks, personal_keys, _note, unsorted, kinds = _assistant_sorted(
            ws, store, cfg, sources[source_id], router, {item.key: facts for _, _, item, facts in found}, go=with_go
        )
        home = _personal_home(store, cfg)
        for req, snap, item, _facts in found:
            if item.key in unsorted:
                still_waiting.add(req.id)
                continue  # the sorting couldn't be run for it: it stays marked and waits for it
            mark = marks.get(item.key)
            if mark is None:
                personal = home if home and item.key in personal_keys else None
                if personal or req.data.get("sort_pending") or item.key in kinds:
                    _file_under(store, req.id, personal, kinds.get(item.key))
                continue
            try:
                with store.transaction() as tx:
                    current, shot = tx.get("request", req.id), tx.get("snapshot", snap.id)
                    tx.update(
                        "snapshot", shot.id, {"set_aside": _set_aside_of(mark)}, _SORTER, read_version=shot.version
                    )
                    tx.update(
                        "request",
                        current.id,
                        {
                            "state": "done",
                            "waiting": f"Set aside: {mark['reason']}",
                            "cause": None,
                            "approval": None,
                            "estimate_usd": None,
                            "set_aside": _set_aside_of(mark),
                            "sort_pending": False,
                        },
                        _SORTER,
                        read_version=current.version,
                    )
                set_aside += 1
            except StoreError:
                continue  # it changed meanwhile (the worker took it, or the person acted); it stays as work
    if pending_only and only is None:
        # A marked request the sorting no longer covers (a rule places it now, the person pulled it back, or the
        # sorting is off) has nothing to wait for.
        for req in store.read().list("request"):
            if (
                req.data.get("sort_pending")
                and req.data["state"] == "queued"
                and req.id not in still_waiting
                and (requests is None or req.id in requests)
            ):
                _file_under(store, req.id, None)
    return set_aside


def _file_under(store: Any, request_id: str, project: str | None, kind: str | None = None) -> None:
    """The sorting answered for a request it isn't setting aside: file it under this project when it names none, as
    the sorting's personal answer does for mail handed in before the first go, keep the kind the sorting gave it
    (`mail_kind`), and clear its `sort_pending` mark. A request that changed meanwhile is left as it is."""
    try:
        with store.transaction() as tx:
            current = tx.get("request", request_id)
            if current is None:
                return
            changes: dict[str, Any] = {}
            if project and not current.data.get("project"):
                changes["project"] = project
            if current.data.get("sort_pending"):
                changes["sort_pending"] = False
            if kind is not None and current.data.get("mail_kind") != kind:
                changes["mail_kind"] = kind
            if changes:
                tx.update("request", current.id, changes, _SORTER, read_version=current.version)
    except StoreError:
        pass


def _carried_sorting(before: Any) -> dict[str, str] | None:
    """What the assistant set aside stays set aside when the item changes: its mark, as a match."""
    mark = before.data.get("set_aside") if before is not None else None
    if mark and mark.get("by") == "assistant" and mark.get("section"):
        return {"rule": mark["rule"], "reason": mark["reason"], "section": mark["section"], "by": "assistant"}
    return None


def _input_text(source: Any, item: SourceItem, change: str, old: str | None, replaces: str | None = None) -> str:
    where = source.label or source.id
    if replaces:
        note = f"This is the current version of the document. It replaces the earlier version {replaces}; it wins.\n\n"
        return note + _input_text(source, item, change, old)
    if change == "new":
        return f"New in {where}: {item.title}\n\n{item.text}"
    diff = difflib.unified_diff(
        (old or "").splitlines(), item.text.splitlines(), "before", "now", n=CONTEXT_LINES, lineterm=""
    )
    shown = "\n".join(list(diff)[2:])
    return f"Changed in {where}: {item.title}\n\nWhat changed:\n{shown}\n\nIt now reads:\n{item.text}"


def _message_dict(message: Any) -> dict[str, Any] | None:
    """A message's details as plain data, the way the snapshot keeps them (categories and participants as lists)."""
    from dataclasses import asdict

    if message is None:
        return None
    from engine.connectors import MESSAGE_PLACES

    return {
        **asdict(message),
        "categories": list(message.categories),
        "participants": list(message.participants),
        "references": list(message.references),
        "where": message.where if message.where in MESSAGE_PLACES else None,
    }


def _set_aside_of(closed: dict[str, str] | None) -> dict[str, str] | None:
    """A match that sets mail aside, as the snapshot keeps it: {section, rule, reason}, and `by` when the assistant's
    sorting made it."""
    if not closed or not closed.get("section"):
        return None
    mark = {"section": closed["section"], "rule": closed["rule"], "reason": closed["reason"]}
    return {**mark, "by": closed["by"]} if closed.get("by") else mark


def _kept_set_aside(before: Any) -> dict[str, str] | None:
    """What the person set aside by hand stays set aside when the item changes."""
    mark = before.data.get("set_aside") if before is not None else None
    return mark if mark and mark.get("by") == "person" else None


#: The data levels from the least private to the most.
DATA_LEVELS = ("open", "internal", "restricted")


def side_data_level(cfg: Any, source: Any) -> tuple[str, list[str]] | None:
    """The level a source takes from the sides it serves, with those sides' ids: the most private level among them
    (the personal project's own, else the one each side sets). None when it serves none that is listed."""
    project = cfg.workspace.project
    levels: dict[str, str] = {}
    for side in source.sides:
        if project.personal and side == project.personal:
            levels[side] = project.personal_data_level
        elif entry := next((e for e in project.sides if e.project == side), None):
            levels[side] = entry.data_level
    if not levels:
        return None
    top = max(levels.values(), key=DATA_LEVELS.index)
    return top, [side for side, level in levels.items() if level == top]


def data_level_source(cfg: Any, source: Any) -> tuple[str, str, list[str]]:
    """How sensitive what a watched source holds is, and where that comes from: the source's own setting ("source"),
    else the most private level of the sides it serves ("side", with those sides' ids), else the one for its kind of
    source ("kind"), else the default for all sources ("default")."""
    if source.data_level:
        return source.data_level, "source", []
    if found := side_data_level(cfg, source):
        return found[0], "side", found[1]
    if level := cfg.watch.connector_data_levels.get(source.connector):
        return level, "kind", []
    return cfg.watch.default_data_level, "default", []


def data_level_of(cfg: Any, source: Any) -> str:
    """How sensitive what a watched source holds is: see `data_level_source`."""
    return data_level_source(cfg, source)[0]


def _details(item: SourceItem) -> dict[str, Any]:
    """What a calendar or mail item is, as the snapshot keeps it."""
    return {
        "link": item.link,
        "changed_at": item.changed_at,
        "event": _event_dict(item.event),
        "message": _message_dict(item.message),
    }


def _event_dict(event: Any) -> dict[str, Any] | None:
    """An event's details as plain data, the way the snapshot keeps them (its lists as lists)."""
    from dataclasses import asdict

    return json.loads(json.dumps(asdict(event))) if event is not None else None


def _change(cfg: Any, source: Any, item: SourceItem, change: str, old: str | None) -> dict[str, Any]:
    """What triage matchers see about a change."""
    before, now = old or "", item.text
    diff = list(difflib.ndiff(before.splitlines(), now.splitlines())) if change == "changed" else []
    return {
        "source": source.id,
        "key": item.key,
        "title": item.title,
        "change": change,
        "author": item.author,
        "before": before,
        "now": now,
        "added": [line[2:] for line in diff if line.startswith("+ ")],
        "removed": [line[2:] for line in diff if line.startswith("- ")],
        "our_accounts": list(cfg.workspace.our_accounts),
        "message": _message_dict(item.message),
    }


def _named_in(name: str | None, accounts: Any) -> bool:
    """Whether a name an item's author is given by is one of these account names, ignoring case and spacing."""
    return bool(name) and " ".join(name.split()).lower() in {" ".join(a.split()).lower() for a in accounts}


def is_own_work(cfg: Any, source: Any, item: SourceItem) -> bool:
    """Whether a change is the person's own work: the source is the person's (its author is the person's id), or the
    change was made under one of the names the person uses. The app's own names are kept apart, so what the app
    published never reads as the person's edit."""
    person = cfg.workspace.user.person
    if person and (source.author == person or getattr(source, "role", None) == "sent"):
        return True
    return _named_in(item.author, own_names(cfg))


def _hand_in(
    ws: Any,
    store: Any,
    tx: Any,
    cfg: Any,
    source: Any,
    item: SourceItem,
    change: str,
    text: str,
    now: datetime,
    closed: dict[str, Any] | None,
    ctx: WriteContext = _WATCHER,
    extra: dict[str, Any] | None = None,
    burst: bool = False,
) -> str:
    """Save the input's text and queue it for the assistant, as outside content: closed at once when a triage rule
    matches, and with any older change to the same item that is still waiting folded in, so they are read once, in
    order. The records are written as `ctx`. `extra`: more fields for the request (a first read taking a source in
    holds it for one go); a request closed at once keeps only its `intake` mark."""
    folded = [] if closed or burst else _waiting_for(tx, source.id, item.key)
    earlier = [_read_text(ws, tx.get("source", r.data["source"]).data["content_hash"]) for r in folded]
    # A sender's limit on any of the messages read together limits them all, to the people every limit holds.
    known = People.from_records(
        {p.id: p.data for p in tx.list("person")},
        cfg.workspace.user.person,
        self_words=language_words(cfg.language, "self_words"),
    )
    limit = audience.narrowest(
        audience.limit_of(t, language_words(cfg.language, "limit_markings"), known) for t in (text, *earlier)
    )
    if folded:
        text = "\n\nThen:\n\n".join([*earlier, text])
    digest = _keep_text(ws, text)
    received = item.message.received if item.message is not None and item.message.received else None
    by_you = is_own_work(cfg, source, item)
    by_us = not by_you and _named_in(item.author, cfg.workspace.our_accounts)
    record = tx.create(
        "source",
        {
            "received_at": received or now.isoformat(),
            "sent_at": received,
            "kind": f"watched:{source.connector}",
            "title": f"{item.title}"[:120],
            "content_hash": digest,
            "trust": "untrusted",
            "projects": [source.project] if source.project else [],
            "sensitivity": data_level_of(cfg, source),
            "url": item.link,
            **({"audience": limit} if limit else {}),
            "watched": {
                "source": source.id,
                "key": item.key,
                "change": change,
                "author": item.author,
                "by_us": by_us,
                "by_you": by_you,
                "credited_to": source.author,
            },
        },
        ctx,
    )
    data: dict[str, Any] = {
        "task": "notes",
        "source": record.id,
        "origin": "input",
        "state": "queued",
        "waiting": STARTING,
        "created_at": now.isoformat(),
    }
    if closed and closed.get("section"):
        data.update(
            state="done",
            waiting=f"Set aside: {closed['reason']}",
            set_aside=_set_aside_of(closed),
        )
    elif closed:
        data.update(state="done", waiting=f"Closed by {closed['rule']}: {closed['reason']}", auto_closed=closed)
    if getattr(source, "role", None) == "deleted":
        data["source_role"] = "deleted"
    if extra:
        data.update({k: v for k, v in extra.items() if not closed or k == "intake"})
    request = tx.create("request", data, ctx)
    for older in folded:
        tx.update(
            "request",
            older.id,
            {"state": "done", "waiting": "Folded into a newer change to the same item", "folded_into": request.id},
            ctx,
            read_version=older.version,
        )
    return request.id


def _waiting_for(tx: Any, source: str, key: str) -> list[Any]:
    """Requests for earlier changes to this item that the assistant hasn't started, oldest first."""
    found = []
    for request in tx.list("request"):
        if request.data["state"] != "queued" or not request.data.get("source"):
            continue
        record = tx.get("source", request.data["source"])
        watched = record.data.get("watched") if record else None
        if watched and watched["source"] == source and watched["key"] == key:
            found.append(request)
    return sorted(found, key=lambda r: str(r.data["created_at"]))


def _same_words(ws: Any, before: Any, text: str, digest: str) -> bool:
    """Whether an item read again says what was saved: the same hash, or saved text that was markup and reads as this
    text."""
    if before.data["content_hash"] == digest:
        return True
    saved = _read_text(ws, before.data["content_hash"])
    return bool(saved) and as_text(saved) == text


def _keep_text(ws: Any, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ws.sources_dir.mkdir(parents=True, exist_ok=True)
    path = ws.sources_dir / f"{digest}.txt"
    if not path.exists():
        write_whole(path, text)
    return digest


def _read_text(ws: Any, digest: str) -> str:
    path = ws.sources_dir / f"{digest}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _record(store: Any, source: str, now: datetime, clock: float, outcome: str, **values: Any) -> None:
    with store.transaction() as tx:
        tx.create(
            "watch_run",
            {
                "source": source,
                "started_at": now.isoformat(),
                "seconds": round(time.monotonic() - clock, 3),
                "outcome": outcome,
                **values,
            },
            WriteContext(actor="watcher", trust="trusted", op="watch.run"),
        )


WHAT_TO_DO = {
    "auth": "Sign in to it again, then it is read on its next turn.",
    "no_access": "Check what it reads (Change, on Connections), or sign in again and allow access to it.",
    "not_found": "Check that it is still there and that its settings on Connections name it right (Change).",
    "outage": "The service it is on seems to be failing; it is tried again on its schedule.",
    "unreadable": "Something it holds stopped the read, so it is tried again on its schedule.",
}


#: What went wrong, by kind of failure, in the app's own words. A connector's detail is shown behind "Show details" and
#: never as the sentence, since it may carry a service's own reply; only a failure the app itself found (`addon`) is its
#: own detail.
WHAT_WENT_WRONG = {
    "auth": "Its sign-in stopped working.",
    "no_access": "It isn't allowed to read that.",
    "not_found": "It couldn't find what it reads.",
    "outage": "The service it reads from isn't answering.",
    "unreadable": "Something it holds couldn't be read.",
}
WENT_WRONG_GENERIC = "It couldn't be read."


def plain_what(kind: str, detail: str | None, own: bool = False) -> str:
    """The first sentence of a problem: the detail when it is in the app's own words (it found the fault itself, or a
    connector it ships wrote it), else the kind's usual sentence."""
    if (own or kind == "addon") and detail:
        return detail
    return WHAT_WENT_WRONG.get(kind, WENT_WRONG_GENERIC)


ADVICE_FILE = Path(__file__).parent / "defaults" / "source_advice.yaml"


@lru_cache(maxsize=1)
def _advice() -> dict[str, str]:
    return yaml.safe_load(ADVICE_FILE.read_text(encoding="utf-8")) or {}


#: The advice that sends the person to a password box: it fits a connection with a password, never one that signed in on
#: the service's own page.
PASSWORD_ADVICE = frozenset(
    f"sources.advice.{key}"
    for key in ("check_credentials", "check_password", "create_app_password", "review_server_message")
)
SIGN_IN_AGAIN = "sources.advice.sign_in_again"


def _sign_in_advice(store: Any, connector: str, advice_key: str | None) -> str | None:
    """The advice a failed read of this connector carries: a connector of an add-on that signs in as the person never
    sends them to a password box (it has none); it says to sign in again."""
    if advice_key in PASSWORD_ADVICE and _signs_in(store, connector):
        return SIGN_IN_AGAIN
    return advice_key


def _signs_in(store: Any, connector: str) -> bool:
    """Whether this connector belongs to an add-on that signs in as the person on the service's own page."""
    if "/" not in connector:
        return False
    plugin = connector.split("/", 1)[0]
    return any(sign.plugin == plugin for sign in store.plugins.sign_ins().values())


def advice_for(kind: str, advice_key: str | None = None) -> str:
    """What to do about a source that failed: the sentence the connector named by wording key, else the kind's usual
    one. The screen words the same key from its own sheet."""
    if advice_key and advice_key in _advice():
        return _advice()[advice_key]
    return WHAT_TO_DO.get(kind, "")


def advice_sentence(key: str) -> str:
    """One sentence of the advice sheet by its wording key; empty when there is none."""
    return _advice().get(key, "")


def _problem(what: str, advice: str) -> str:
    """What went wrong and what to do, as sentences (no second full stop when the words already end one)."""
    what = what if what.endswith((".", "!", "?")) else what + "."
    what = what[:1].upper() + what[1:]  # a service's own words begin lower case; a sentence begins with a capital
    return f"{what} {advice}".strip()


def _own_words(source: Any, err: ConnectorError) -> bool:
    """Whether a failure's detail is in the app's own words (the app found the fault, a connector it ships wrote it, or
    it is the answer-too-large notice), so a screen may say it as a sentence."""
    return bool(err.detail) and (source.connector in CORE or isinstance(err, AddonMissing | AnswerTooLarge))


def _maybe_ask(store: Any, cfg: Any, source: Any, err: ConnectorError) -> str:
    """The problem in words; at the configured count of failures in a row, one question to the person."""
    where = source.label or source.id
    own = _own_words(source, err)
    what = f"{where} can't be read: {err.detail}" if own else f"{where} can't be read"
    problem = _problem(what, advice_for(err.kind, err.advice_key))
    if failures_in_a_row(store, source.id) != cfg.watch.failures_before_asking:
        return problem
    # A connection that signs in as the person is told on Today as its account's one line, with the button that signs in
    # again: a question for each of its connections would say the same thing again.
    if source.account or _signs_in(store, source.connector):
        return problem
    pm = cfg.workspace.user.person
    if not pm or store.read().get("person", pm) is None:
        return problem
    with store.transaction() as tx:
        tx.create(
            "question",
            {
                "to": pm,
                "title": f"{where} can't be read",
                "text": problem,
                "kind": "decision",
                "resolves": {"kind": "watch", "source": source.id},
            },
            WriteContext(actor="watcher", trust="trusted", op="watch.problem"),
        )
    return problem


def _tell_unreadable(store: Any, cfg: Any, source: Any, unreadable: Sequence[Any]) -> None:
    """What a read found but couldn't read is never a silent skip: one open decision for the person per source names
    each item and why, kept until the person drops it (a later read adds what it finds to the same one). Nothing is
    written when the person isn't known, or when the open one already names every item."""
    if not unreadable:
        return
    pm = cfg.workspace.user.person
    if not pm or store.read().get("person", pm) is None:
        return
    open_one = next(
        (
            q
            for q in store.read().list("question")
            if (q.data.get("resolves") or {}).get("kind") == "watch_unreadable"
            and q.data["resolves"].get("source") == source.id
            and q.data["status"] == "open"
        ),
        None,
    )
    items = list((open_one.data["resolves"].get("items") or []) if open_one else [])
    known = {i["key"] for i in items}
    items += [{"key": u.key, "reason": u.reason} for u in unreadable if u.key not in known]
    if open_one is not None and len(items) == len(known):
        return
    where = source.label or source.id
    count = len(items)
    title = f"Look at the {count} item{'s' if count != 1 else ''} in {where} that couldn't be read"
    text = (
        "These weren't read, so nothing in them has been looked at: "
        + "; ".join(f"{i['key']} ({i['reason']})" for i in items)
        + f". The rest of {where} was read. Open them in the service itself."
    )
    resolves = {"kind": "watch_unreadable", "source": source.id, "items": items}
    with store.transaction() as tx:
        if open_one is None:
            tx.create(
                "question",
                {"to": pm, "title": title, "text": text, "kind": "decision", "resolves": resolves},
                WriteContext(actor="watcher", trust="trusted", op="watch.unreadable"),
            )
        else:
            tx.update(
                "question",
                open_one.id,
                {"title": title, "text": text, "resolves": resolves},
                WriteContext(actor="watcher", trust="trusted", op="watch.unreadable"),
                read_version=open_one.version,
            )


def record_crash(store: Any, source_id: str, now: datetime, err: BaseException) -> None:
    """A read that stopped with an error nothing expected, recorded as a failed read of its source (so the line that
    says a source can't be read, and the count of failures in a row, apply) and never as a stop of the other sources.
    The error's own words are not kept: they may quote what was being read."""
    log.error("Reading source %s failed: %s", source_id, type(err).__name__, exc_info=err)
    _record(
        store,
        source_id,
        now,
        time.monotonic(),
        "failed",
        error_kind="unreadable",
        error="something in it couldn't be read",
    )


def _close_question(store: Any, source: str) -> None:
    """A read that works ends the question about that source."""
    open_ones = [
        q
        for q in store.read().list("question")
        if (q.data.get("resolves") or {}).get("kind") == "watch"
        and q.data["resolves"].get("source") == source
        and q.data["status"] == "open"
    ]
    if not open_ones:
        return
    with store.transaction() as tx:
        for question in open_ones:
            tx.update(
                "question",
                question.id,
                {"status": "dropped"},
                WriteContext(actor="watcher", trust="trusted", op="watch.recovered"),
                read_version=question.version,
            )


def hand_in_recent(
    ws: Any, store: Any, cfg: Any, source_id: str, now: datetime | None = None, router: Any = None
) -> list[str]:
    """Hand the assistant what a source already holds from the recent past or near future (its `first_run_hours`
    around now) that it hasn't been handed yet: the person asks for this after a first read that only noted what was
    there. Triage rules and the assistant's sorting of mail apply as for any change. Returns the requests made. It
    waits for a read of the same source under way, and holds that source's lock while it works, so the same item is
    never handed in twice."""
    with _read_lock(ws, source_id):
        made = _hand_in_recent(ws, store, cfg, source_id, now, router)
        _after_mail(ws, store, cfg, now or datetime.now(UTC))
        return made


def hand_in_snapshot(ws: Any, store: Any, cfg: Any, snapshot_id: str, now: datetime | None = None) -> str | None:
    """Hand the assistant an item the source holds that was never handed in (it was noted on a first read, or set
    aside), whatever its age. Returns the request made, or None when the item or its source isn't there."""
    snap = store.read().get("snapshot", snapshot_id)
    source = next((s for s in cfg.watch.sources if snap is not None and s.id == snap.data["source"]), None)
    if snap is None or source is None or snap.data.get("deleted"):
        return None
    with _read_lock(ws, source.id):
        with store.transaction() as tx:
            made = hand_in_snapshot_in(ws, store, tx, cfg, snapshot_id, now)
        _after_mail(ws, store, cfg, now or datetime.now(UTC))
        return made


def hand_in_snapshot_in(
    ws: Any,
    store: Any,
    tx: Any,
    cfg: Any,
    snapshot_id: str,
    now: datetime | None = None,
    ctx: WriteContext = _WATCHER,
) -> str | None:
    """`hand_in_snapshot` inside a transaction the caller holds, so it commits or rolls back with the caller's other
    changes, and its records are written as `ctx` (so a change that holds them can undo them). The caller takes the
    source's read lock first when it can, as `hand_in_snapshot` does."""
    snap = tx.get("snapshot", snapshot_id)
    source = next((s for s in cfg.watch.sources if snap is not None and s.id == snap.data["source"]), None)
    if snap is None or source is None or snap.data.get("deleted"):
        return None
    data = snap.data
    from engine.connectors import EventDetails

    item = SourceItem(
        data["key"],
        data["title"],
        _read_text(ws, data["content_hash"]),
        author=data.get("author"),
        changed_at=data.get("changed_at"),
        link=data.get("link"),
        event=EventDetails.from_dict(data["event"]) if data.get("event") else None,
        message=_message_of(data.get("message")),
    )
    return _hand_in(
        ws,
        store,
        tx,
        cfg,
        source,
        item,
        "new",
        _input_text(source, item, "new", None),
        now or datetime.now(UTC),
        None,
        ctx,
    )


def item_of_snapshot(ws: Any, data: dict[str, Any]) -> SourceItem:
    """A noted item as the connector's own type, with its saved text."""
    from engine.connectors import EventDetails

    return SourceItem(
        data["key"],
        data["title"],
        _read_text(ws, data["content_hash"]),
        author=data.get("author"),
        changed_at=data.get("changed_at"),
        link=data.get("link"),
        event=EventDetails.from_dict(data["event"]) if data.get("event") else None,
        message=_message_of(data.get("message")),
    )


def _message_of(details: dict[str, Any] | None) -> Any:
    """A snapshot's kept message details as the connector's own type."""
    from engine.connectors import MessageDetails

    if not details:
        return None
    return MessageDetails(**{**details, "categories": tuple(details.get("categories") or ())})


def _hand_in_recent(
    ws: Any, store: Any, cfg: Any, source_id: str, now: datetime | None, router: Any = None
) -> list[str]:
    now = now or datetime.now(UTC)
    source = next((s for s in cfg.watch.sources if s.id == source_id), None)
    if source is None:
        raise StoreError(f"there is no source {source_id}")
    window = timedelta(hours=source.first_run_hours)
    return _hand_in_window(
        ws, store, cfg, source_id, now, router, lambda data: is_recent(data, data.get("changed_at"), now, window)
    )


def _hand_in_window(
    ws: Any,
    store: Any,
    cfg: Any,
    source_id: str,
    now: datetime,
    router: Any,
    accept: Any,
    extra: dict[str, Any] | None = None,
    sort: bool = True,
) -> list[str]:
    """Hand the assistant the items a source holds that were never handed in and that `accept` takes (it is given
    the snapshot's data), with the usual triage and, when `sort`, the assistant's sorting of mail. `extra` goes on
    each request made."""
    from engine import capture
    from engine.connectors import EventDetails

    source = next((s for s in cfg.watch.sources if s.id == source_id), None)
    if source is None:
        raise StoreError(f"there is no source {source_id}")
    handed = {
        (s.data.get("watched") or {}).get("key")
        for s in store.read().list("source")
        if (s.data.get("watched") or {}).get("source") == source_id
    }
    pending: list[tuple[Any, SourceItem, dict[str, str] | None, bool]] = []
    messages = MessageIndex(store.read())
    unplaced: dict[str, dict[str, Any]] = {}
    plain = entry_rules.Plain(store.read(), cfg, source_id)
    for snap in store.read().find("snapshot", {"source": source_id}):
        data = snap.data
        if data.get("gone") or data.get("deleted") or data.get("set_aside") or data["key"] in handed:
            continue
        if data.get("closed_by") == capture.CAPTURED:
            continue  # handed in already, as the person's own capture
        if not accept(data):
            continue
        item = SourceItem(
            data["key"],
            data["title"],
            _read_text(ws, data["content_hash"]),
            author=data.get("author"),
            changed_at=data.get("changed_at"),
            link=data.get("link"),
            event=EventDetails.from_dict(data["event"]) if data.get("event") else None,
            message=_message_of(data.get("message")),
        )
        if plain.of(item):
            continue  # a plain calendar entry is kept by rule, so the assistant has nothing to read
        if item.message is not None and messages.taken_elsewhere(snap):
            continue  # another mailbox holds this same message (its Message-ID): one message, one item
        facts = _change(cfg, source, item, "new", None)
        closed, kept, personal = classify_placed(store, cfg, facts)
        if closed is None and not kept and item.message is not None:
            unplaced[item.key] = facts
        pending.append((snap, item, closed, personal))
    marks, personal_keys, _note, unsorted_keys, kinds = (
        _assistant_sorted(ws, store, cfg, source, router, unplaced) if sort else ({}, set(), None, set(), {})
    )
    home = _personal_home(store, cfg)
    made = []
    for snap, item, closed, by_rule in pending:
        sorted_aside = marks.get(item.key) if closed is None else None
        filed = {"project": home} if home and (by_rule or item.key in personal_keys) else None
        if item.key in unsorted_keys and closed is None and not sorted_aside:
            filed = {**(filed or {}), "sort_pending": True}
        if item.key in kinds and closed is None and not sorted_aside:
            filed = {**(filed or {}), "mail_kind": kinds[item.key]}
        with store.transaction() as tx:
            if sorted_aside:
                tx.update(
                    "snapshot", snap.id, {"set_aside": _set_aside_of(sorted_aside)}, _WATCHER, read_version=snap.version
                )
            made.append(
                _hand_in(
                    ws,
                    store,
                    tx,
                    cfg,
                    source,
                    item,
                    "new",
                    _input_text(source, item, "new", None),
                    now,
                    closed or sorted_aside,
                    extra={**(extra or {}), **(filed or {})} or None,
                )
            )
    return made
