"""A year of message headers read after a mail source's first sign-in (design 6.32, 6.22).

After a mail source's first read, the core asks the connector (when it can: `registrar.connector(..., headers=fn)`)
for the newest `watch.first_headers_sample_items` headers at once and the rest of the messages from
`watch.first_headers_days` back to the day that read began later, in slices in the account's lane (`sweep_slice`),
and keeps each as a `mail_header` record: who it was from and to, when, where it ended up and its subject, never its
text. Nothing here calls AI and nothing is handed in: a header is not an input, a request or a packet's outside
content, and the sorting never sees it. The contact tally reads the kept headers like any message's details, and
`habit_lines` gathers counts for the first look at the person's habits: which senders' mail is deleted unopened, what
recurs, and where messages ended up. The rules only gather; every judgment about what a habit means is the
assistant's."""

from __future__ import annotations

import logging
import re
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine import contact_tally
from engine import people_suggestions as ps
from engine.connectors import MESSAGE_PLACES, ConnectorError
from engine.source_intake import CONTINUES
from engine.storage import StoreError, WriteContext

log = logging.getLogger(__name__)

_KEEP = WriteContext(actor="watcher", trust="untrusted", op="watch.headers")
_SWEEP = WriteContext(actor="engine", trust="trusted", op="watch.header_sweep")
_CHUNK = 500
_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_SHOWN_SUBJECT = 60


def asker(store: Any, source: Any) -> Any:
    """How the source is asked for headers alone: its plugin connector's `headers` function as the plugin host wraps
    it, or the core mailbox connector's own header fetch, or None when the connector can't be asked (a connector that
    says nothing about headers works as before)."""
    from engine.connectors import header_mail

    core = header_mail(source.connector)
    if core is not None:
        return core
    plugins = getattr(store, "plugins", None)
    connector = plugins.connectors().get(source.connector) if plugins is not None else None
    if connector is None or getattr(connector, "headers", None) is None:
        return None
    return plugins.header_mail(connector, source.account)


def _fetch(
    ws: Any, store: Any, cfg: Any, source: Any, now: datetime, since: date, before: date, limit: int, room: int
) -> tuple[int, int, date | None, ConnectorError | None]:
    """Ask the source once for the newest `limit` headers of these days and keep them, no more than `room` (a message a
    snapshot or an earlier header already stands for is not kept again). Returns how many were kept, how many the source
    gave, the day of the oldest, and the connector's error when it stopped (what it held is kept). Nothing is recorded
    as a read."""
    asking = asker(store, source)
    if asking is None:
        return 0, 0, None, None
    from engine import source_intake, watch
    from engine.connectors import ConnectorContext, Poll, skipped_counts

    context = ConnectorContext(
        workspace_root=ws.root, now=now, timezone=cfg.workspace.user.timezone, hosted=cfg.server.mode == "hosted"
    )
    try:
        answer = asking(_settings_of(store, source), since, before, limit, context)
    except ConnectorError as err:
        return 0, 0, None, err
    items, unreadable = (answer.items, answer.unreadable) if isinstance(answer, Poll) else (answer, [])
    kept = keep(store, source, items, now, room)
    if unreadable:
        source_intake.add_older_skipped(store, source.id, skipped_counts(unreadable))
        watch._tell_unreadable(store, cfg, source, unreadable)
    days = [d for d in map(source_intake._item_day, items) if d is not None]
    stop = answer.stopped if isinstance(answer, Poll) else None
    return kept, len(items) + len(unreadable), (min(days) if days else None), stop


def _settings_of(store: Any, source: Any) -> Any:
    from engine.connectors import CORE

    if source.connector in CORE:
        return CORE[source.connector].settings.model_validate(source.settings)
    connector = store.plugins.connectors()[source.connector]
    return connector.settings.model_validate(source.settings)


def keep(store: Any, source: Any, items: list[Any], now: datetime, room: int | None = None) -> int:
    """Keep each item's details and subject as a header: nothing of its text or files, and nothing for a message the
    source already holds (a snapshot or an earlier header of the same key), and no more than `room` of them."""
    from engine.watch import _message_dict

    view = store.read()
    held = {s.data["key"] for s in view.find("snapshot", {"source": source.id})}
    held |= {h.data["key"] for h in view.find("mail_header", {"source": source.id})}
    fresh = []
    for item in items:
        message = _message_dict(item.message)
        if message is None or item.key in held:
            continue
        if room is not None and len(fresh) >= room:
            break
        held.add(item.key)
        fresh.append(
            {"source": source.id, "key": item.key, "title": item.title, "message": message, "seen_at": now.isoformat()}
        )
    for start in range(0, len(fresh), _CHUNK):
        with store.transaction() as tx:
            for data in fresh[start : start + _CHUNK]:
                tx.create("mail_header", data, _KEEP)
    return len(fresh)


def read_after_first(
    ws: Any, store: Any, cfg: Any, source: Any, now: datetime, clock: float, before: date | None = None
) -> None:
    """What a mail source's first read is followed by: only the newest `watch.first_headers_sample_items` headers of
    the year (`before` is the day the first read's own mail starts from, else the day after today). The rest of the
    days back are queued for the account's lane (`sweep_slice`). Nothing here is recorded as the source's read: a stop
    or a failure never becomes a failed read, it only changes when and whether the rest is read."""
    days = cfg.watch.first_headers_days
    if days <= 0 or asker(store, source) is None:
        return
    until = before or (now.date() + timedelta(days=1))
    since = until - timedelta(days=days)
    cap, sample = (
        cfg.watch.first_headers_max_items,
        min(cfg.watch.first_headers_sample_items, cfg.watch.first_headers_max_items),
    )
    kept = got = 0
    oldest: date | None = None
    stop = None
    try:
        if sample > 0:
            kept, got, oldest, stop = _fetch(ws, store, cfg, source, now, since, until, sample, cap)
    except StoreError as err:
        log.warning("The headers of %s couldn't be kept: %s", source.id, err)
        return
    rest_before = until
    if stop is not None and stop.kind not in CONTINUES:
        log.warning("The sample of headers of %s stopped (%s) and is not carried on", source.id, stop.kind)
        return
    if stop is None and sample > 0 and (got < sample or oldest is None or oldest <= since):
        return  # the sample was everything the source holds of those days
    if oldest is not None:
        rest_before = min(until, oldest + timedelta(days=1))
    state = _sweep_state(cfg, since, rest_before, cap - kept, cfg.watch.full_read_page_items, now, kept)
    if stop is not None:
        state = _stopped(cfg, state, stop, now, progressed=kept > 0)
    _set_sweep(store, source.id, state)


def _sweep_state(
    cfg: Any, since: date, before: date, left: int, size: int, now: datetime, taken: int = 0, tries: int = 0
) -> dict[str, Any]:
    return {
        "since": since.isoformat(),
        "before": before.isoformat(),
        "left": max(left, 0),
        "size": size,
        "kind": "queued",
        "at": now.isoformat(),
        "tries": tries,
        "taken": taken,
        "gave_up": False,
        "stopped_at": now.isoformat(),
    }


def _stopped(cfg: Any, state: dict[str, Any], stop: ConnectorError, now: datetime, progressed: bool) -> dict[str, Any]:
    """The state after the service slowed the read down or failed: a wait is never a try, a failure or no network is,
    and only when nothing moved on in a row; after the last try it waits for the person."""
    tries = int(state.get("tries", 0))
    if stop.kind == "throttled":
        tries = 0 if progressed else tries
        wait = stop.retry_after if stop.retry_after is not None else cfg.watch.older_read_throttle_minutes * 60
    else:
        tries = 1 if progressed else tries + 1
        wait = cfg.watch.older_read_retry_minutes * 60
    state = {
        **state,
        "kind": stop.kind,
        "tries": tries,
        "stopped_at": now.isoformat(),
        "wait_seconds": stop.retry_after,
    }
    if tries > cfg.watch.older_read_tries:
        return {**state, "at": None, "gave_up": True}
    return {**state, "at": (now + timedelta(seconds=wait)).isoformat(), "gave_up": False}


def _sweep_run(view: Any, source_id: str) -> Any | None:
    """The record that keeps a source's header sweep: its intake read, else its newest first read."""
    from engine import source_intake

    run = source_intake.intake_run(view, source_id)
    if run is not None:
        return run
    firsts = [r for r in view.find("watch_run", {"source": source_id}) if r.data.get("outcome") == "baseline"]
    return max(firsts, key=lambda r: str(r.data.get("started_at"))) if firsts else None


def _set_sweep(store: Any, source_id: str, state: dict[str, Any] | None) -> None:
    run = _sweep_run(store.read(), source_id)
    if run is None:
        log.warning("No first read of %s to keep its headers still to read on", source_id)
        return
    changes: dict[str, Any] = {"header_sweep": state}
    if state is None and run.data.get("header_sweep"):
        # The sweep ended (read to its end, or dropped for the person): the look at who the person deals with
        # looks again.
        changes["header_sweep_finished_at"] = store.clock()
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        tx.update("watch_run", run.id, changes, _SWEEP, read_version=current.version)


def sweep_waiting(view: Any, source_id: str) -> dict[str, Any] | None:
    """Where a source's rest of headers waits to be read, or None."""
    run = _sweep_run(view, source_id)
    return dict(run.data["header_sweep"]) if run is not None and run.data.get("header_sweep") else None


def sweep_due(view: Any, cfg: Any, now: datetime) -> list[str]:
    """The sources whose rest of headers is to be read and whose time has come."""
    due = []
    for source in cfg.watch.sources:
        waiting = sweep_waiting(view, source.id)
        if waiting and waiting.get("at") and now >= datetime.fromisoformat(str(waiting["at"])):
            due.append(source.id)
    return due


def sweep_slice(ws: Any, store: Any, cfg: Any, source_id: str, now: datetime) -> bool:
    """Read one page of the rest of a source's headers, under its read lock (nothing is done while it is being read),
    when its time has come. A stop keeps what was read and carries on at its time; the source's own read is never
    touched. Returns whether a page was asked for."""
    from engine import watch

    source = next((s for s in cfg.watch.sources if s.id == source_id), None)
    lock = watch._read_lock(ws, source_id)
    if source is None or not lock.acquire(blocking=False):
        return False
    try:
        state = sweep_waiting(store.read(), source_id)
        if state is None or not state.get("at") or now < datetime.fromisoformat(str(state["at"])):
            return False
        since, before = date.fromisoformat(state["since"]), date.fromisoformat(state["before"])
        left, size = int(state["left"]), int(state["size"])
        if left <= 0 or since >= before or asker(store, source) is None:
            _set_sweep(store, source_id, None)
            return False
        try:
            kept, got, oldest, stop = _fetch(ws, store, cfg, source, now, since, before, size, left)
        except StoreError as err:
            log.warning("The headers of %s couldn't be kept: %s", source_id, err)
            return True
        taken = int(state.get("taken", 0)) + kept
        moved = min(before, oldest + timedelta(days=1)) if oldest is not None else before
        state = {**state, "left": left - kept, "taken": taken, "before": moved.isoformat()}
        if kept:
            state["kept_at"] = now.isoformat()  # the look at who the person deals with may read what came in
        if stop is not None:
            if stop.kind not in CONTINUES:
                log.warning("The rest of the headers of %s stopped (%s) and is not carried on", source_id, stop.kind)
                _set_sweep(store, source_id, None)
            else:
                _set_sweep(store, source_id, _stopped(cfg, state, stop, now, progressed=kept > 0))
            return True
        if got < size or oldest is None or oldest <= since or left - kept <= 0:
            _set_sweep(store, source_id, None)  # the rest is read
            return True
        # A day that holds more than a page is asked again with a larger page; headers already kept are not kept twice.
        if moved >= before and size >= cfg.watch.first_headers_max_items:
            _set_sweep(store, source_id, None)  # one day holds more than the most there is room for
            return True
        size = min(size * 2, cfg.watch.first_headers_max_items) if moved >= before else cfg.watch.full_read_page_items
        _set_sweep(store, source_id, {**state, "size": size, "kind": "reading", "tries": 0, "at": now.isoformat()})
        return True
    finally:
        lock.release()


# ---- what the headers show, as counts ----------------------------------------------------------------------------


def _when(data: dict[str, Any]) -> date | None:
    stamp = (data.get("message") or {}).get("received") or data.get("seen_at")
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment.astimezone(UTC) if moment.tzinfo else moment).date()


def _pattern(title: str) -> str:
    """A subject with its reply marks and numbers taken out, so a message that repeats under a new number is one."""
    plain = _PREFIX.sub("", title or "")
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", plain)).strip().lower()


def _steady(days: list[date]) -> int | None:
    """The interval in days when the dates repeat at a steady one (at least three, each gap within a quarter of the
    middle gap, at least a day), else None."""
    days = sorted(set(days))
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    if len(days) < 3 or not gaps:
        return None
    middle = statistics.median(gaps)
    if middle < 1:
        return None
    room = max(1.0, middle * 0.25)
    return round(middle) if all(abs(g - middle) <= room for g in gaps) else None


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("|", "/")).strip()


def habit_lines(store: Any, cfg: Any, only: set[str] | None = None) -> list[str]:
    """Short lines of counts about the received mail the app holds the details of (kept headers and snapshots), for
    the first judgment run's packet: which senders' mail the person deletes unopened, where each sender's messages
    ended up, and what recurs (the same sender and a similar subject at a steady interval). Only senders with at
    least `person_look_min_messages` messages are counted, the most dealt with first, at most `person_look_entries`
    for each kind of line. Facts to weigh, never verdicts; subject words are outside content and the caller marks
    them so. `only` limits the senders to those addresses (the ones the look reads)."""
    settings = cfg.dispatch.knowledge
    sources = ps._mail_sources(store, cfg)
    person = cfg.workspace.user.person
    own = ps._own_addresses(store, cfg, sources)
    view = store.read()
    places: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unopened: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    series: dict[tuple[str, str], list[date]] = defaultdict(list)
    shown: dict[tuple[str, str], str] = {}
    for s in sources:
        if person and s.author == person:
            continue  # sent mail says who the person writes to, which the tally already gives
        for held in contact_tally.held_messages(view, s.id):
            message = held.data["message"]
            display, address = ps._parsed(message.get("sender") or "")
            if not address or address in own:
                continue
            totals[address] += 1
            names.setdefault(address, ps._name_of(re.sub(r"\s+", " ", display.replace('"', "")).strip(), address))
            where = message.get("where") if message.get("where") in MESSAGE_PLACES else "unknown"
            places[address][where] += 1
            if where == "deleted" and message.get("unread") is True:
                unopened[address] += 1
            title = held.data.get("title") or ""
            day = _when(held.data)
            if day is not None and _pattern(title):
                series[(address, _pattern(title))].append(day)
                shown.setdefault((address, _pattern(title)), title)
    floor, cap = settings.person_look_min_messages, settings.person_look_entries
    ranked = sorted(
        (a for a in totals if totals[a] >= floor and (only is None or a in only)), key=lambda a: (-totals[a], a)
    )
    lines: list[str] = []
    gone = [a for a in ranked if unopened[a]]
    gone.sort(key=lambda a: (-unopened[a], a))
    for a in gone[:cap]:
        lines.append(f"deleted unopened | {a} | {_one_line(names[a])} | {unopened[a]} of {totals[a]} messages")
    for a in ranked[:cap]:
        known = {k: v for k, v in places[a].items() if k != "unknown"}
        if not known:
            continue  # the service doesn't say where this sender's messages were
        spread = ", ".join(f"{k} {v}" for k, v in sorted(known.items()))
        lines.append(f"where they ended up | {a} | {_one_line(names[a])} | {spread}")
    repeats = []
    for (a, pattern), days in series.items():
        if a not in ranked:
            continue
        interval = _steady(days)
        if interval is not None:
            repeats.append((-len(days), a, pattern, interval, max(days)))
    for count, a, pattern, interval, last in sorted(repeats)[:cap]:
        subject = _one_line(shown[(a, pattern)])[:_SHOWN_SUBJECT]
        lines.append(f'recurs | {a} | "{subject}" | {-count} times, about every {interval} days, last {last}')
    return lines
